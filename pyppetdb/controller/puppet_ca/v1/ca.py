import logging
from fastapi import APIRouter, Request, Response, HTTPException
from pyppetdb.config import Config
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
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
        self._ca_service = ca_service
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

        try:
            cert = await self._crud_certificates.get(
                space_id="puppet-ca",
                certname=nodename,
                fields=["status", "certificate"],
            )
            if cert.status == "signed" and cert.certificate:
                return Response(content=cert.certificate, media_type="text/plain")
            else:
                raise HTTPException(
                    status_code=404, detail="Certificate not yet signed"
                )
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="Certificate not found")

    async def get_certificate_request(self, nodename: str, request: Request):
        try:
            cert = await self._crud_certificates.get(
                space_id="puppet-ca", certname=nodename, fields=["csr"]
            )
            if cert.csr:
                return Response(content=cert.csr, media_type="text/plain")
            raise HTTPException(status_code=404, detail="CSR not found")
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="CSR not found")

    async def submit_certificate_request(self, nodename: str, request: Request):
        body = await request.body()
        csr_pem = body.decode()

        await self._crud_certificates.submit_csr(
            space_id="puppet-ca", certname=nodename, csr_pem=csr_pem, fields=["id"]
        )

        if self._config.ca.autoSign:
            self._log.info(f"Auto-signing CSR for {nodename} in space puppet-ca")
            try:
                await self._ca_service.update_certificate_status(
                    "puppet-ca", nodename, CACertificatePut(status="signed")
                )
            except Exception as e:
                self._log.error(f"Failed to auto-sign CSR for {nodename}: {e}")

        return Response(content="CSR submitted", media_type="text/plain")

    async def get_certificate_status(self, nodename: str, request: Request):
        try:
            cert = await self._crud_certificates.get(
                space_id="puppet-ca", certname=nodename
            )
            return {
                "name": cert.id,
                "state": cert.status,
                "fingerprint": cert.fingerprint.sha256 if cert.fingerprint else None,
                "fingerprints": {
                    "SHA1": cert.fingerprint.sha1 if cert.fingerprint else None,
                    "SHA256": cert.fingerprint.sha256 if cert.fingerprint else None,
                    "default": cert.fingerprint.sha256 if cert.fingerprint else None,
                },
            }
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="Certificate not found")

    async def update_certificate_status(self, nodename: str, request: Request):
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
            self._log.error(f"Failed to update certificate status: {e}")
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
            self._log.error(f"Failed to get CRL: {e}")
            raise HTTPException(status_code=500, detail="Failed to get CRL")
