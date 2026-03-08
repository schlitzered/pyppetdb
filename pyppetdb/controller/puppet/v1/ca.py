import logging
from fastapi import APIRouter, Request, Response, HTTPException
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.errors import ResourceNotFound

class ControllerPuppetV1CA:
    def __init__(
        self,
        log: logging.Logger,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
    ):
        self._log = log
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
        self._router = APIRouter(prefix="/puppet-ca/v1", tags=["puppet-ca"])

        self._router.add_api_route("/certificate/{nodename}", self.get_certificate, methods=["GET"])
        self._router.add_api_route("/certificate_request/{nodename}", self.get_certificate_request, methods=["GET"])
        self._router.add_api_route("/certificate_request/{nodename}", self.submit_certificate_request, methods=["PUT"])
        self._router.add_api_route("/certificate_revocation_list/ca", self.get_crl, methods=["GET"])

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
            # Fetch CA cert
            try:
                space = await self._crud_spaces.get(space_id, fields=["authority_id"])
                ca = await self._crud_authorities.get(space.authority_id, fields=["certificate"])
                return Response(content=ca.certificate, media_type="text/plain")
            except ResourceNotFound:
                raise HTTPException(status_code=404, detail="CA not found for space")
        
        try:
            cert = await self._crud_certificates.get(space_id=space_id, certname=nodename, fields=["status", "certificate"])
            if cert.status == "signed" and cert.certificate:
                return Response(content=cert.certificate, media_type="text/plain")
            else:
                raise HTTPException(status_code=404, detail="Certificate not yet signed")
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="Certificate not found")

    async def get_certificate_request(self, nodename: str, request: Request):
        space_id = await self._get_space_id(request)
        try:
            cert = await self._crud_certificates.get(space_id=space_id, certname=nodename, fields=["csr"])
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
            space_id=space_id,
            certname=nodename,
            csr_pem=csr_pem,
            fields=["id"]
        )
        return Response(content="CSR submitted", media_type="text/plain")

    async def get_crl(self, request: Request):
        space_id = await self._get_space_id(request)
        try:
            crl_pem = await self._crud_certificates.get_crl(space_id)
            return Response(content=crl_pem, media_type="text/plain")
        except ResourceNotFound:
            raise HTTPException(status_code=404, detail="CRL not found for space")
        except Exception as e:
            self._log.error(f"Failed to generate CRL: {e}")
            raise HTTPException(status_code=500, detail="Failed to generate CRL")
