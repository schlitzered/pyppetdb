import logging
import asyncio
from typing import List, Optional, Set
from datetime import datetime, timezone

from pyppetdb.config import Config
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.errors import ResourceNotFound, QueryParamValidationError
from pyppetdb.model.ca_authorities import (
    CAAuthorityPost,
    CAAuthorityGet,
    CAAuthorityGetMulti,
)
from pyppetdb.model.ca_spaces import CASpacePost, CASpaceGet
from pyppetdb.model.ca_certificates import CACertificateGet, CACertificatePut
from pyppetdb.model.common import MetaMulti


class CAService:
    def __init__(
        self,
        log: logging.Logger,
        config: Config,
        crud_authorities: CrudCAAuthorities,
        crud_spaces: CrudCASpaces,
        crud_certificates: CrudCACertificates,
    ):
        self._log = log
        self._config = config
        self._crud_authorities = crud_authorities
        self._crud_spaces = crud_spaces
        self._crud_certificates = crud_certificates

    async def refresh_crl(self, ca_id: str) -> None:
        ca = await self._crud_authorities.get(ca_id, fields=["internal", "certificate"])
        if not ca.internal:
            return

        ca_key = await self._crud_authorities.get_private_key(ca_id)

        # Optimized: fetch only serials and dates
        revoked_cas = await self._crud_authorities.get_revoked(parent_id=ca_id)

        spaces_multi = await self._crud_spaces.search_by_ca(ca_id=ca_id)
        space_ids = [s["id"] for s in spaces_multi]
        revoked_certs = await self._crud_certificates.get_revoked_for_spaces(space_ids)

        await self._crud_authorities.sync_crl(
            ca_id=ca_id,
            ca_cert_pem=ca.certificate.encode(),
            ca_key_pem=ca_key,
            revoked_certs=revoked_cas + revoked_certs,
        )

    async def refresh_expiring_crls(self) -> None:
        self._log.info("Checking for expiring CRLs...")
        ca_ids = await self._crud_authorities.find_expiring_crls(
            threshold_hours=24 * 30
        )

        for ca_id in ca_ids:
            if await self._crud_authorities.lock_crl_acquire(ca_id):
                self._log.info(f"Refreshing CRL for CA '{ca_id}'")
                try:
                    await self.refresh_crl(ca_id)
                except Exception as e:
                    self._log.error(f"Failed to refresh CRL for CA '{ca_id}': {e}")
                    await self._crud_authorities.lock_crl_release(ca_id)
                # Success: sync_crl already unlocks via update_crl
            else:
                self._log.debug(
                    f"CRL refresh for CA '{ca_id}' is already locked by another process"
                )

    async def crl_refresh_worker(self) -> None:
        while True:
            try:
                await self.refresh_expiring_crls()
            except Exception as e:
                self._log.error(f"Error in CRL refresh worker: {e}")
            await asyncio.sleep(43200)  # Run once every 12 hours

    async def create_authority(
        self, _id: str, payload: CAAuthorityPost
    ) -> CAAuthorityGet:
        return await self._crud_authorities.create(
            _id=_id, payload=payload, fields=["id"]
        )

    async def delete_authority(self, ca_id: str) -> None:
        # 1. Check if used by any space (current or history)
        spaces = await self._crud_spaces.search_by_ca(ca_id=ca_id)
        if spaces:
            space_ids = [s["id"] for s in spaces]
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' is still in use by one or more spaces: {', '.join(space_ids)}"
            )

        # 2. Check if it's a parent of another CA
        count_cas = await self._crud_authorities.count({"parent_id": ca_id})
        if count_cas > 0:
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' is still a parent of one or more CA Authorities"
            )

        # 3. Check if any certificates are still associated with this CA
        # (Technically covered by space check, but safe to keep)
        count_certs = await self._crud_certificates.count(
            {"issuer": {"$regex": f"CN={ca_id}"}}
        )
        if count_certs > 0:
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' cannot be deleted because it still has {count_certs} certificates associated with it"
            )

        await self._crud_authorities.delete(_id=ca_id)
        await self._crud_spaces.remove_ca_from_history(ca_id=ca_id)

    async def update_certificate_status(
        self, space_id: str, cn: str, data: CACertificatePut, fields: list = None
    ) -> CACertificateGet:
        """Update certificate status by space_id and CN (common name)."""
        if fields is None:
            fields = ["id", "status", "ca_id"]

        if data.status == "signed":
            space = await self._crud_spaces.get(space_id, fields=["ca_id"])
            ca_cert = await self._crud_authorities.get(
                space.ca_id, fields=["certificate"]
            )
            ca_key = await self._crud_authorities.get_private_key(space.ca_id)
            return await self._crud_certificates.sign(
                space_id=space_id,
                cn=cn,
                ca_cert_pem=ca_cert.certificate.encode(),
                ca_key_pem=ca_key,
                fields=fields,
            )
        elif data.status == "revoked":
            # Find the signed cert by space_id and CN, then revoke by serial
            cert_doc = await self._crud_certificates.coll.find_one(
                {"space_id": space_id, "cn": cn, "status": "signed"}
            )
            if not cert_doc:
                raise QueryParamValidationError(
                    msg=f"No signed certificate found for CN '{cn}' in space '{space_id}'"
                )
            cert = await self._crud_certificates.revoke(
                _id=cert_doc["id"], fields=fields
            )
            space = await self._crud_spaces.get(space_id, fields=["ca_id"])
            await self.refresh_crl(space.ca_id)
            return cert

    async def update_certificate_status_by_ca(
        self, ca_id: str, serial: str, data: CACertificatePut, fields: list = None
    ) -> CACertificateGet:
        """Update certificate status by CA ID and serial number."""
        if fields is None:
            fields = ["id", "status", "ca_id"]

        if data.status == "signed":
            raise QueryParamValidationError(
                msg="Cannot sign a certificate by serial number. Use space_id and CN instead."
            )
        elif data.status == "revoked":
            cert = await self._crud_certificates.revoke(_id=serial, fields=fields)
            await self.refresh_crl(ca_id)
            return cert

    async def revoke_authority(self, ca_id: str) -> CAAuthorityGet:
        ca = await self._crud_authorities.get(ca_id, fields=["parent_id"])
        revoked_ca = await self._crud_authorities.revoke(_id=ca_id)
        if ca.parent_id:
            await self.refresh_crl(ca.parent_id)
        return revoked_ca

    async def get_certificate_chain(self, space_id: str) -> str:
        """
        Get certificate chain for a space, including current CA, historic CAs, and their parent chains.

        Args:
            space_id: The space ID to get certificates for

        Returns:
            Concatenated certificate PEM data as string
        """
        space = await self._crud_spaces.get(space_id, fields=["ca_id", "ca_id_history"])
        ca_ids = [space.ca_id] + space.ca_id_history

        full_chain_parts = []
        processed_certs = set()

        for ca_id in ca_ids:
            try:
                ca = await self._crud_authorities.get(
                    ca_id, fields=["certificate", "chain"]
                )

                # Add CA certificate
                if ca.certificate not in processed_certs:
                    full_chain_parts.append(ca.certificate)
                    processed_certs.add(ca.certificate)

                # Add parent certificates from chain
                for parent_cert in ca.chain:
                    if parent_cert not in processed_certs:
                        full_chain_parts.append(parent_cert)
                        processed_certs.add(parent_cert)
            except ResourceNotFound:
                self._log.warning(
                    f"CA Authority '{ca_id}' not found during certificate chain generation"
                )
                continue

        return "\n".join(full_chain_parts)

    async def get_crl_chain(self, space_id: str) -> bytes:
        """
        Get CRL chain for a space, including CRLs for current CA, historic CAs, and all parent CAs.

        Args:
            space_id: The space ID to get CRLs for

        Returns:
            Concatenated CRL PEM data as bytes
        """
        space = await self._crud_spaces.get(space_id, fields=["ca_id", "ca_id_history"])

        # Start with current CA and historic CAs for this space
        ca_ids_to_process = [space.ca_id] + space.ca_id_history
        processed_ca_ids = set()
        crl_chain_pem = b""

        while ca_ids_to_process:
            ca_id = ca_ids_to_process.pop(0)
            if ca_id in processed_ca_ids:
                continue
            processed_ca_ids.add(ca_id)

            try:
                ca = await self._crud_authorities.get(
                    ca_id, fields=["crl", "internal", "parent_id"]
                )
            except ResourceNotFound:
                self._log.warning(
                    f"CA Authority '{ca_id}' not found during CRL chain generation"
                )
                continue

            # Always add parent CA to chain if it exists
            if ca.parent_id and ca.parent_id not in processed_ca_ids:
                ca_ids_to_process.append(ca.parent_id)

            # Skip external CAs (they don't have CRLs)
            if not ca.internal:
                continue

            # Get CRL for this CA
            if not ca.crl:
                self._log.error(f"Internal CA '{ca_id}' is missing CRL data")
                continue

            crl_chain_pem += ca.crl.crl_pem.encode()

        return crl_chain_pem
