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

    async def _get_space_id(self, request: Request) -> str:
        # Standard Puppet Agents don't know about spaces.
        # We always use the 'puppet-ca' space for this compatibility API.
        return "puppet-ca"

    async def get_certificate(self, nodename: str, request: Request):
        space_id = await self._get_space_id(request)
        if nodename == "ca":
            # Fetch CA certs for the current authority and all historical ones
            try:
                space = await self._crud_spaces.get(space_id, fields=["ca_id", "ca_id_history"])
                ca_ids = [space.ca_id] + space.ca_id_history

                full_chain_parts = []
                processed_certs = set()

                for ca_id in ca_ids:
                    try:
                        ca = await self._crud_authorities.get(ca_id)
                        if ca.certificate not in processed_certs:
                            full_chain_parts.append(ca.certificate)
                            processed_certs.add(ca.certificate)

                        for parent_cert in ca.chain:
                            if parent_cert not in processed_certs:
                                full_chain_parts.append(parent_cert)
                                processed_certs.add(parent_cert)
                    except ResourceNotFound:
                        continue

                return Response(
                    content="\n".join(full_chain_parts), media_type="text/plain"
                )
            except ResourceNotFound:
                raise HTTPException(status_code=404, detail="Space not found")

        try:
            cert = await self._crud_certificates.get(
                space_id=space_id, certname=nodename, fields=["status", "certificate"]
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
        space_id = await self._get_space_id(request)
        try:
            cert = await self._crud_certificates.get(
                space_id=space_id, certname=nodename, fields=["csr"]
            )
            if cert.csr:
                return Response(content=cert.csr, media_type="text/plain")
            raise HTTPException(status_code=404, detail="CSR not found")
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="CSR not found")

    async def submit_certificate_request(self, nodename: str, request: Request):
        space_id = await self._get_space_id(request)
        body = await request.body()
        csr_pem = body.decode()

        await self._crud_certificates.submit_csr(
            space_id=space_id, certname=nodename, csr_pem=csr_pem, fields=["id"]
        )

        if self._config.ca.autoSign:
            self._log.info(f"Auto-signing CSR for {nodename} in space {space_id}")
            try:
                await self._ca_service.update_certificate_status(
                    space_id, nodename, CACertificatePut(status="signed")
                )
            except Exception as e:
                self._log.error(f"Failed to auto-sign CSR for {nodename}: {e}")
                # We don't fail the request if auto-signing fails, as the CSR is already submitted.
                # But maybe we should? Puppet agent might expect it to be signed if it's auto-signing.
                # However, submit_csr is a PUT request that just says "I've uploaded this".
                # If it's not signed immediately, the agent will just poll later.

        return Response(content="CSR submitted", media_type="text/plain")

    async def get_certificate_status(self, nodename: str, request: Request):
        space_id = await self._get_space_id(request)
        try:
            cert = await self._crud_certificates.get(
                space_id=space_id, certname=nodename
            )
            # Puppet expects a specific JSON format for status
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
        space_id = await self._get_space_id(request)
        data_json = await request.json()
        desired_state = data_json.get("desired_state")

        try:
            if desired_state == "signed":
                await self._ca_service.update_certificate_status(
                    space_id, nodename, CACertificatePut(status="signed")
                )
                return Response(status_code=204)
            elif desired_state == "revoked":
                await self._ca_service.update_certificate_status(
                    space_id, nodename, CACertificatePut(status="revoked")
                )
                return Response(status_code=204)
            else:
                raise HTTPException(
                    status_code=400, detail=f"Invalid desired_state: {desired_state}"
                )
        except Exception as e:
            self._log.error(f"Failed to update certificate status: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def _get_crl_cached(self, ca_id: str) -> bytes:
        try:
            ca = await self._crud_authorities.get(ca_id, fields=["crl"])
            if ca.crl:
                return ca.crl.crl_pem.encode()
            # No CRL exists, generate it
            await self._ca_service.sync_crl_for_authority(ca_id)
            ca = await self._crud_authorities.get(ca_id, fields=["crl"])
            return ca.crl.crl_pem.encode() if ca.crl else b""
        except ResourceNotFound:
            await self._ca_service.sync_crl_for_authority(ca_id)
            ca = await self._crud_authorities.get(ca_id, fields=["crl"])
            return ca.crl.crl_pem.encode() if ca.crl else b""

    async def get_crl(
        self,
        request: Request,
    ):
        include_chain = (
            request.query_params.get("include_chain", "true").lower() == "true"
        )
        space_id = await self._get_space_id(request)
        try:
            space = await self._crud_spaces.get(space_id, fields=["ca_id", "ca_id_history"])

            # Start with CA and its history for this space
            ca_ids_to_process = [space.ca_id] + space.ca_id_history
            processed_ca_ids = set()
            crl_chain_pem = b""

            while ca_ids_to_process:
                ca_id = ca_ids_to_process.pop(0)
                if ca_id in processed_ca_ids:
                    continue
                processed_ca_ids.add(ca_id)

                try:
                    ca = await self._crud_authorities.get(ca_id)
                except ResourceNotFound:
                    self._log.warning(
                        f"CA Authority '{ca_id}' not found during CRL chain generation"
                    )
                    continue

                # Add parent to process queue if chain is requested
                if (
                    include_chain
                    and ca.parent_id
                    and ca.parent_id not in processed_ca_ids
                ):
                    ca_ids_to_process.append(ca.parent_id)

                if not ca.internal:
                    continue

                crl_pem = await self._get_crl_cached(ca_id=ca_id)
                crl_chain_pem += crl_pem

            return Response(content=crl_chain_pem, media_type="text/plain")
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="CRL not found for space")
        except Exception as e:
            self._log.error(f"Failed to get CRL: {e}")
            raise HTTPException(status_code=500, detail="Failed to get CRL")
