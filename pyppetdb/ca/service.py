import logging
import asyncio
from typing import List, Optional, Set
from datetime import datetime, timezone

from pyppetdb.config import Config
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.crud.ca_crls import CrudCACRLs
from pyppetdb.errors import ResourceNotFound, QueryParamValidationError
from pyppetdb.model.ca_authorities import CAAuthorityPost, CAAuthorityGet
from pyppetdb.model.ca_spaces import CASpacePost, CASpaceGet
from pyppetdb.model.ca_certificates import CACertificateGet, CACertificateStatusPut

class CAService:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
        crud_crls: CrudCACRLs
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates
        self._crud_crls = crud_crls

    async def sync_crl_for_authority(self, ca_id: str) -> None:
        ca = await self._crud_authorities.get(ca_id)
        if not ca.internal:
            return

        ca_key = await self._crud_authorities.get_private_key(ca_id)
        
        # Optimized: fetch only serials and dates
        revoked_cas = await self._crud_authorities.get_revoked(parent_id=ca_id)
        
        spaces_multi = await self._crud_spaces.search_by_ca(ca_id=ca_id)
        space_ids = [s["id"] for s in spaces_multi]
        revoked_certs = await self._crud_certificates.get_revoked_for_spaces(space_ids)
        
        await self._crud_crls.sync_crl(
            ca_id=ca_id,
            ca_cert_pem=ca.certificate.encode(),
            ca_key_pem=ca_key,
            revoked_certs=revoked_cas + revoked_certs
        )

    async def refresh_expiring_crls(self) -> None:
        self._log.info("Checking for expiring CRLs...")
        ca_ids = await self._crud_crls.find_expiring_crls(threshold_hours=4)
        
        for ca_id in ca_ids:
            if await self._crud_crls.acquire_lock(ca_id):
                self._log.info(f"Refreshing CRL for CA '{ca_id}'")
                try:
                    await self.sync_crl_for_authority(ca_id)
                except Exception as e:
                    self._log.error(f"Failed to refresh CRL for CA '{ca_id}': {e}")
                    await self._crud_crls.unlock(ca_id)
                # Success: sync_crl already unlocks via update_crl
            else:
                self._log.debug(f"CRL refresh for CA '{ca_id}' is already locked by another process")

    async def crl_refresh_worker(self) -> None:
        while True:
            try:
                await self.refresh_expiring_crls()
            except Exception as e:
                self._log.error(f"Error in CRL refresh worker: {e}")
            await asyncio.sleep(3600) # Run once every hour

    async def create_authority(self, _id: str, payload: CAAuthorityPost) -> CAAuthorityGet:
        return await self._crud_authorities.create(_id=_id, payload=payload)

    async def delete_authority(self, ca_id: str) -> None:
        # 1. Check if used by any space (current or history)
        spaces = await self._crud_spaces.search_by_ca(ca_id=ca_id)
        if spaces:
            space_ids = [s["id"] for s in spaces]
            raise QueryParamValidationError(msg=f"CA Authority '{ca_id}' is still in use by one or more spaces: {', '.join(space_ids)}")

        # 2. Check if it's a parent of another CA
        count_cas = await self._crud_authorities.count({"parent_id": ca_id})
        if count_cas > 0:
            raise QueryParamValidationError(msg=f"CA Authority '{ca_id}' is still a parent of one or more CA Authorities")

        # 3. Check if any certificates are still associated with this CA
        # (Technically covered by space check, but safe to keep)
        count_certs = await self._crud_certificates.count({"issuer": {"$regex": f"CN={ca_id}"}}) 
        if count_certs > 0:
            raise QueryParamValidationError(msg=f"CA Authority '{ca_id}' cannot be deleted because it still has {count_certs} certificates associated with it")

        await self._crud_authorities.delete(_id=ca_id)
        await self._crud_crls.delete(ca_id=ca_id)
        await self._crud_spaces.remove_ca_from_history(ca_id=ca_id)

    async def update_certificate_status(self, space_id: str, cert_id: str, data: CACertificateStatusPut) -> CACertificateGet:
        if data.status == "signed":
            space = await self._crud_spaces.get(space_id)
            ca_cert = await self._crud_authorities.get(space.authority_id)
            ca_key = await self._crud_authorities.get_private_key(space.authority_id)
            return await self._crud_certificates.sign(
                space_id=space_id, 
                certname=cert_id, 
                ca_cert_pem=ca_cert.certificate.encode(),
                ca_key_pem=ca_key
            )
        elif data.status == "revoked":
            cert = await self._crud_certificates.revoke(space_id=space_id, certname=cert_id)
            space = await self._crud_spaces.get(space_id)
            await self.sync_crl_for_authority(space.authority_id)
            return cert

    async def revoke_authority(self, ca_id: str) -> CAAuthorityGet:
        ca = await self._crud_authorities.get(ca_id)
        revoked_ca = await self._crud_authorities.revoke(_id=ca_id)
        if ca.parent_id:
            await self.sync_crl_for_authority(ca.parent_id)
        return revoked_ca
