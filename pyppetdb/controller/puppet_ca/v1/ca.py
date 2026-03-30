import logging
from fastapi import APIRouter, Request, Response, HTTPException
from pyppetdb.config import Config
from pyppetdb.authorize import AuthorizeClientCert
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.service import CAService
from pyppetdb.errors import ResourceNotFound
from pyppetdb.model.ca_certificates import CACertificatePut


class ControllerPuppetCaV1CA:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        ca_service: CAService,
        authorize_client_cert: AuthorizeClientCert,
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
        self._ca_service = ca_service
        self._authorize_client_cert = authorize_client_cert
        self._router = APIRouter(tags=["puppet-ca"])

        self._router.add_api_route(
            "/certificate/{nodename}", self.get_certificate, methods=["GET"]
        )
        self._router.add_api_route(
            "/certificate_request/{nodename}",
            self.get_certificate_request,
            methods=["GET"],
        )
        self._router.add_api_route(
            "/certificate_request/{nodename}",
            self.submit_certificate_request,
            methods=["PUT"],
        )
        self._router.add_api_route(
            "/certificate_status/{nodename}",
            self.get_certificate_status,
            methods=["GET"],
        )
        self._router.add_api_route(
            "/certificate_status/{nodename}",
            self.update_certificate_status,
            methods=["PUT"],
        )
        self._router.add_api_route(
            "/certificate_revocation_list/ca", self.get_crl, methods=["GET"]
        )
        self._router.add_api_route(
            "/certificate_renewal", self.certificate_renewal, methods=["POST"]
        )

    @property
    def log(self):
        return self._log

    @property
    def authorize_client_cert(self):
        return self._authorize_client_cert

    @property
    def router(self):
        return self._router

    async def get_certificate(self, nodename: str, request: Request):
        if nodename == "ca":
            try:
                cert_chain = await self._ca_service.get_certificate_chain("puppet-ca")
                return Response(content=cert_chain, media_type="text/plain")
            except ResourceNotFound:
                raise HTTPException(status_code=404, detail="Space not found")

        cert_doc = await self._crud_certificates.coll.find_one(
            {"space_id": "puppet-ca", "cn": nodename, "status": "signed"}
        )
        if not cert_doc or not cert_doc.get("certificate"):
            raise HTTPException(status_code=404, detail="Certificate not found")

        return Response(content=cert_doc["certificate"], media_type="text/plain")

    async def get_certificate_request(self, nodename: str, request: Request):
        await self.authorize_client_cert.require_cn_trusted(request)
        cert_doc = await self._crud_certificates.coll.find_one(
            {"space_id": "puppet-ca", "cn": nodename, "status": "requested"}
        )
        if not cert_doc or not cert_doc.get("csr"):
            raise HTTPException(status_code=404, detail="CSR not found")

        return Response(content=cert_doc["csr"], media_type="text/plain")

    async def submit_certificate_request(self, nodename: str, request: Request):
        from pyppetdb.errors import QueryParamValidationError

        body = await request.body()
        csr_pem = body.decode()

        try:
            await self._ca_service.submit_certificate_request(
                space_id="puppet-ca",
                csr_pem=csr_pem,
                fields=["id"],
                cn=nodename,
            )
        except QueryParamValidationError as e:
            raise HTTPException(status_code=400, detail=e.detail)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

        if self._config.ca.autoSign:
            self.log.info(f"Auto-signing CSR for {nodename} in space puppet-ca")
            try:
                await self._ca_service.sign_certificate(
                    space_id="puppet-ca", cn=nodename
                )
            except Exception as e:
                self.log.error(f"Failed to auto-sign CSR for {nodename}: {e}")

        return Response(content="CSR submitted", media_type="text/plain")

    async def get_certificate_status(self, nodename: str, request: Request):
        await self.authorize_client_cert.require_cn_trusted(request)
        cert_doc = await self._crud_certificates.coll.find_one(
            {"space_id": "puppet-ca", "cn": nodename}
        )
        if not cert_doc:
            raise HTTPException(status_code=404, detail="Certificate not found")

        return {
            "name": cert_doc["cn"],
            "state": cert_doc["status"],
            "fingerprint": cert_doc.get("fingerprint", {}).get("sha256"),
            "fingerprints": {
                "SHA1": cert_doc.get("fingerprint", {}).get("sha1"),
                "SHA256": cert_doc.get("fingerprint", {}).get("sha256"),
                "default": cert_doc.get("fingerprint", {}).get("sha256"),
            },
        }

    async def update_certificate_status(self, nodename: str, request: Request):
        await self.authorize_client_cert.require_cn_trusted(request)
        data_json = await request.json()
        desired_state = data_json.get("desired_state")

        try:
            if desired_state == "signed":
                await self._ca_service.update_certificate_status(
                    "puppet-ca", nodename, CACertificatePut(status="signed")
                )
                return Response(status_code=204)
            elif desired_state == "revoked":
                await self._ca_service.update_certificate_status(
                    "puppet-ca", nodename, CACertificatePut(status="revoked")
                )
                return Response(status_code=204)
            else:
                raise HTTPException(
                    status_code=400, detail=f"Invalid desired_state: {desired_state}"
                )
        except Exception as e:
            self.log.error(f"Failed to update certificate status: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_crl(
        self,
    ):
        try:
            crl_chain_pem = await self._ca_service.get_crl_chain("puppet-ca")
            return Response(content=crl_chain_pem, media_type="text/plain")
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="CRL not found for space")
        except Exception as e:
            self.log.error(f"Failed to get CRL: {e}")
            raise HTTPException(status_code=500, detail="Failed to get CRL")

    async def certificate_renewal(self, request: Request):
        try:
            cert_info = await self._authorize_client_cert.get_cert_info(request)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        nodename = cert_info["cn"]

        try:
            new_cert = await self._ca_service.renew_certificate(
                space_id="puppet-ca", cn=nodename
            )
            return Response(content=new_cert.certificate, media_type="text/plain")
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="Certificate not found")
        except Exception as e:
            self.log.error(f"Failed to renew certificate for {nodename}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
