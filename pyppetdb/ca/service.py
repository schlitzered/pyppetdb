import logging
import asyncio
import datetime
import uuid
import pymongo

from pyppetdb.config import Config
from pyppetdb.crud.ca_authorities import CrudCAAuthorities
from pyppetdb.crud.ca_spaces import CrudCASpaces
from pyppetdb.crud.ca_certificates import CrudCACertificates
from pyppetdb.ca.utils import CAUtils
from pyppetdb.errors import ResourceNotFound, QueryParamValidationError
from pyppetdb.model.ca_authorities import (
    CAAuthorityPost,
    CAAuthorityGet,
)
from pyppetdb.model.ca_certificates import CACertificateGet, CACertificatePut
from pyppetdb.model.ca_spaces import CASpaceGet, CASpacePost, CASpacePut


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

        revoked_cas = await self._crud_authorities.get_revoked(parent_id=ca_id)

        revoked_certs = await self._crud_certificates.get_revoked_for_ca(ca_id=ca_id)

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
            await asyncio.sleep(43200)

    async def create_authority(
        self, _id: str, payload: CAAuthorityPost, fields: list = None
    ) -> CAAuthorityGet:
        if fields is None:
            fields = ["id"]
        if payload.certificate and payload.private_key:
            internal = False
            cert_pem = payload.certificate.encode()
            key_pem = payload.private_key.encode()
            chain = payload.external_chain or []
        elif payload.parent_id:
            internal = True
            parent_ca = await self._crud_authorities.get(
                payload.parent_id, fields=["certificate", "chain"]
            )
            parent_key = await self._crud_authorities.get_private_key(payload.parent_id)
            cert_pem, key_pem = CAUtils.sign_ca(
                cn=payload.cn,
                ca_cert_pem=parent_ca.certificate.encode(),
                ca_key_pem=parent_key,
                organization=payload.organization,
                organizational_unit=payload.organizational_unit,
                country=payload.country,
                state=payload.state,
                locality=payload.locality,
                validity_days=payload.validity_days,
            )
            chain = [parent_ca.certificate] + parent_ca.chain
        else:
            internal = True
            cert_pem, key_pem = CAUtils.generate_ca(
                cn=payload.cn,
                organization=payload.organization,
                organizational_unit=payload.organizational_unit,
                country=payload.country,
                state=payload.state,
                locality=payload.locality,
                validity_days=payload.validity_days,
            )
            chain = []

        info = CAUtils.get_cert_info(cert_pem)
        encrypted_key = self._crud_authorities.protector.encrypt_string(
            key_pem.decode()
        )

        data = {
            "id": _id,
            "parent_id": payload.parent_id,
            "certificate": cert_pem.decode(),
            "private_key_encrypted": encrypted_key,
            "internal": internal,
            "chain": chain,
            "status": "active",
            **info,
        }

        if internal:
            crl_pem, next_update = CAUtils.generate_crl(
                ca_cert_pem=cert_pem, ca_key_pem=key_pem, revoked_certs=[]
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            from pyppetdb.model.ca_authorities import CACRL

            data["crl"] = CACRL(
                crl_pem=crl_pem.decode(),
                generation=1,
                updated_at=now,
                next_update=next_update,
                locked_at=None,
            ).model_dump()

        return await self._crud_authorities.insert(payload=data, fields=fields)

    async def _validate_ca_usage(self, ca_id: str, operation: str) -> None:
        spaces = await self._crud_spaces.search_by_ca(ca_id=ca_id)
        if spaces:
            space_ids = [s["id"] for s in spaces]
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' cannot be {operation} because it is still in use by one or more spaces: {', '.join(space_ids)}"
            )

        count_cas = await self._crud_authorities.count(
            {"parent_id": ca_id, "status": "active"}
        )
        if count_cas > 0:
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' cannot be {operation} because it is still a parent of {count_cas} active CA Authority/ies"
            )

        count_certs = await self._crud_certificates.count(
            {"ca_id": ca_id, "status": "signed"}
        )
        if count_certs > 0:
            raise QueryParamValidationError(
                msg=f"CA Authority '{ca_id}' cannot be {operation} because it still has {count_certs} active certificate(s) associated with it"
            )

    async def delete_authority(self, ca_id: str) -> None:
        await self._validate_ca_usage(ca_id=ca_id, operation="deleted")
        await self._crud_authorities.delete(_id=ca_id)
        await self._crud_spaces.remove_ca_from_history(ca_id=ca_id)

    async def create_space(
        self, _id: str, payload: CASpacePost, fields: list = None
    ) -> CASpaceGet:
        if fields is None:
            fields = ["id"]
        data = payload.model_dump()
        data["id"] = _id
        data["ca_id_history"] = []
        return await self._crud_spaces.insert(payload=data, fields=fields)

    async def update_space(
        self, _id: str, payload: CASpacePut, fields: list = None
    ) -> CASpaceGet:
        if fields is None:
            fields = ["id"]
        current = await self._crud_spaces.get(_id, fields=["ca_id", "ca_id_history"])
        data = payload.model_dump()
        if data["ca_id"] != current.ca_id:
            if current.ca_id not in current.ca_id_history:
                current.ca_id_history.append(current.ca_id)
            if data["ca_id"] in current.ca_id_history:
                current.ca_id_history.remove(data["ca_id"])
            data["ca_id_history"] = current.ca_id_history

        return await self._crud_spaces.update(
            query={"id": _id}, payload=data, fields=fields
        )

    async def delete_space(self, _id: str) -> None:
        await self._crud_spaces.delete(query={"id": _id})

    async def submit_certificate_request(
        self, space_id: str, csr_pem: str, fields: list = None, cn: str = None
    ) -> CACertificateGet:
        if fields is None:
            fields = ["id", "status", "ca_id"]

        try:
            csr_info = CAUtils.get_csr_info(csr_pem.encode())
        except Exception as e:
            raise QueryParamValidationError(msg=f"Invalid CSR: {e}")

        csr_cn = csr_info["cn"]

        if cn and cn != csr_cn:
            raise QueryParamValidationError(
                msg=f"CSR CN '{csr_cn}' does not match nodename '{cn}'"
            )

        space = await self._crud_spaces.get(space_id, fields=["ca_id"])

        query = {"space_id": space_id, "cn": csr_cn, "status": "requested"}
        payload = {
            "id": str(uuid.uuid4().int),
            "ca_id": space.ca_id,
            "csr": csr_pem,
            "created": datetime.datetime.now(datetime.timezone.utc),
        }

        # Check if already exists to keep ID
        existing = await self._crud_certificates.coll.find_one(query)
        if existing:
            payload.pop("id")

        return await self._crud_certificates.update(
            query=query, payload=payload, fields=fields, upsert=True
        )

    async def update_certificate_status(
        self, space_id: str, cn: str, data: CACertificatePut, fields: list = None
    ) -> CACertificateGet | None:
        if data.status == "signed":
            return await self.sign_certificate(
                space_id=space_id, cn=cn, fields=fields
            )
        elif data.status == "revoked":
            return await self.revoke_certificate(
                space_id=space_id, cn=cn, fields=fields
            )
        else:
            raise QueryParamValidationError(msg=f"Invalid status: {data.status}")

    async def sign_certificate(
        self, space_id: str, cn: str, fields: list = None
    ) -> CACertificateGet:
        if fields is None:
            fields = ["id", "status", "ca_id"]

        cert_data = await self._crud_certificates.coll.find_one(
            {"space_id": space_id, "cn": cn, "status": "requested"}
        )
        if not cert_data:
            raise QueryParamValidationError(
                msg=f"No pending CSR found for CN '{cn}' in space '{space_id}'"
            )

        space = await self._crud_spaces.get(space_id, fields=["ca_id"])
        ca_cert = await self._crud_authorities.get(space.ca_id, fields=["certificate"])
        ca_key = await self._crud_authorities.get_private_key(space.ca_id)

        cert_pem = CAUtils.sign_csr(
            csr_pem=cert_data["csr"].encode(),
            ca_cert_pem=ca_cert.certificate.encode(),
            ca_key_pem=ca_key,
            serial_number=int(cert_data["id"]),
            validity_days=self._config.ca.certificateValidityDays,
        )

        info = CAUtils.get_cert_info(cert_pem)

        payload = {"status": "signed", "certificate": cert_pem.decode(), **info}

        return await self._crud_certificates.update(
            query={"_id": cert_data["_id"]}, payload=payload, fields=fields
        )

    async def revoke_certificate(
        self, space_id: str, cn: str, fields: list = None
    ) -> CACertificateGet:
        if fields is None:
            fields = ["id", "status", "ca_id"]

        cert_doc = await self._crud_certificates.coll.find_one(
            {"space_id": space_id, "cn": cn, "status": "signed"}
        )
        if not cert_doc:
            raise QueryParamValidationError(
                msg=f"No signed certificate found for CN '{cn}' in space '{space_id}'"
            )

        payload = {
            "status": "revoked",
            "revocation_date": datetime.datetime.now(datetime.timezone.utc),
        }

        cert = await self._crud_certificates.update(
            query={"id": cert_doc["id"]}, payload=payload, fields=fields
        )

        space = await self._crud_spaces.get(space_id, fields=["ca_id"])
        await self.refresh_crl(space.ca_id)
        return cert

    async def renew_certificate(
        self, space_id: str, cn: str, fields: list = None
    ) -> CACertificateGet:
        if fields is None:
            fields = ["id", "status", "ca_id", "certificate"]

        cert_data = await self._crud_certificates.coll.find_one(
            {"space_id": space_id, "cn": cn, "status": "signed"},
            sort=[("not_after", pymongo.DESCENDING)],
        )
        if not cert_data:
            raise QueryParamValidationError(
                msg=f"No signed certificate found for CN '{cn}' in space '{space_id}'"
            )

        space = await self._crud_spaces.get(space_id, fields=["ca_id"])
        ca_cert = await self._crud_authorities.get(space.ca_id, fields=["certificate"])
        ca_key = await self._crud_authorities.get_private_key(space.ca_id)

        new_serial = uuid.uuid4().int

        new_cert_pem = CAUtils.renew_cert(
            cert_pem=cert_data["certificate"].encode(),
            ca_cert_pem=ca_cert.certificate.encode(),
            ca_key_pem=ca_key,
            serial_number=new_serial,
            validity_days=self._config.ca.certificateValidityDays,
        )

        info = CAUtils.get_cert_info(new_cert_pem)

        payload = {
            "id": str(new_serial),
            "space_id": space_id,
            "ca_id": cert_data["ca_id"],
            "cn": cn,
            "status": "signed",
            "certificate": new_cert_pem.decode(),
            "created": datetime.datetime.now(datetime.timezone.utc),
            **info,
        }

        new_cert = await self._crud_certificates.insert(payload=payload, fields=fields)

        # Mark old certificate as revoked
        await self._crud_certificates.update(
            query={"_id": cert_data["_id"]},
            payload={
                "status": "revoked",
                "revocation_date": datetime.datetime.now(datetime.timezone.utc),
            },
            fields=["id"],
        )

        await self.refresh_crl(space.ca_id)
        return new_cert

    async def update_certificate_status_by_ca(
        self, ca_id: str, serial: str, data: CACertificatePut, fields: list = None
    ) -> CACertificateGet | None:
        if fields is None:
            fields = ["id", "status", "ca_id"]

        if data.status == "signed":
            raise QueryParamValidationError(
                msg="Cannot sign a certificate by serial number. Use space_id and CN instead."
            )
        elif data.status == "revoked":
            payload = {
                "status": "revoked",
                "revocation_date": datetime.datetime.now(datetime.timezone.utc),
            }
            cert = await self._crud_certificates.update(
                query={"id": serial}, payload=payload, fields=fields
            )
            await self.refresh_crl(ca_id)
            return cert

    async def revoke_authority(self, ca_id: str) -> CAAuthorityGet:
        await self._validate_ca_usage(ca_id=ca_id, operation="revoked")
        ca = await self._crud_authorities.get(ca_id, fields=["parent_id"])

        payload = {
            "status": "revoked",
            "revocation_date": datetime.datetime.now(datetime.timezone.utc),
        }

        revoked_ca = await self._crud_authorities.update(
            query={"id": ca_id},
            payload=payload,
            fields=["status", "revocation_date"],
        )

        if ca.parent_id:
            await self.refresh_crl(ca.parent_id)
        return revoked_ca

    async def get_certificate_chain(self, space_id: str) -> str:
        space = await self._crud_spaces.get(space_id, fields=["ca_id", "ca_id_history"])
        ca_ids = [space.ca_id] + space.ca_id_history

        full_chain_parts = []
        processed_certs = set()

        for ca_id in ca_ids:
            try:
                ca = await self._crud_authorities.get(
                    ca_id, fields=["certificate", "chain"]
                )

                if ca.certificate not in processed_certs:
                    full_chain_parts.append(ca.certificate)
                    processed_certs.add(ca.certificate)

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
        space = await self._crud_spaces.get(space_id, fields=["ca_id", "ca_id_history"])

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

            if ca.parent_id and ca.parent_id not in processed_ca_ids:
                ca_ids_to_process.append(ca.parent_id)

            if not ca.internal:
                continue

            if not ca.crl:
                self._log.error(f"Internal CA '{ca_id}' is missing CRL data")
                continue

            crl_chain_pem += ca.crl.crl_pem.encode()

        return crl_chain_pem
