# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import uuid
from typing import Any
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


class CAUtils:
    @staticmethod
    def generate_csr(
        cn: str,
        organization: str = "PyppetDB",
        organizational_unit: str = "Nodes",
        country: str = "DE",
        state: Optional[str] = "Hessen",
        locality: Optional[str] = None,
        alt_names: Optional[List[str]] = None,
    ) -> Tuple[bytes, bytes]:
        """Generate a CSR and private key."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )

        name_parts = [
            x509.NameAttribute(
                oid=NameOID.COMMON_NAME,
                value=cn,
            ),
            x509.NameAttribute(
                oid=NameOID.ORGANIZATION_NAME,
                value=organization,
            ),
            x509.NameAttribute(
                oid=NameOID.ORGANIZATIONAL_UNIT_NAME,
                value=organizational_unit,
            ),
            x509.NameAttribute(
                oid=NameOID.COUNTRY_NAME,
                value=country,
            ),
        ]
        if state:
            name_parts.append(
                x509.NameAttribute(
                    oid=NameOID.STATE_OR_PROVINCE_NAME,
                    value=state,
                )
            )
        if locality:
            name_parts.append(
                x509.NameAttribute(
                    oid=NameOID.LOCALITY_NAME,
                    value=locality,
                )
            )

        builder = x509.CertificateSigningRequestBuilder()
        builder = builder.subject_name(
            name=x509.Name(
                attributes=name_parts,
            ),
        )

        if alt_names:
            san = x509.SubjectAlternativeName(
                general_names=[
                    x509.DNSName(
                        value=name,
                    )
                    for name in alt_names
                ],
            )
            builder = builder.add_extension(
                extval=san,
                critical=False,
            )

        csr = builder.sign(
            private_key=private_key,
            algorithm=hashes.SHA256(),
        )

        csr_pem = csr.public_bytes(
            encoding=serialization.Encoding.PEM,
        )
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return csr_pem, key_pem

    @staticmethod
    def generate_ca(
        cn: str,
        organization: str = "PyppetDB",
        organizational_unit: str = "CA",
        country: str = "DE",
        state: Optional[str] = "Hessen",
        locality: Optional[str] = None,
        validity_days: int = 3650,
    ) -> Tuple[bytes, bytes]:
        """Generate a self-signed CA certificate and private key."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )

        name_parts = [
            x509.NameAttribute(
                oid=NameOID.COMMON_NAME,
                value=cn,
            ),
            x509.NameAttribute(
                oid=NameOID.ORGANIZATION_NAME,
                value=organization,
            ),
            x509.NameAttribute(
                oid=NameOID.ORGANIZATIONAL_UNIT_NAME,
                value=organizational_unit,
            ),
            x509.NameAttribute(
                oid=NameOID.COUNTRY_NAME,
                value=country,
            ),
        ]
        if state:
            name_parts.append(
                x509.NameAttribute(
                    oid=NameOID.STATE_OR_PROVINCE_NAME,
                    value=state,
                )
            )
        if locality:
            name_parts.append(
                x509.NameAttribute(
                    oid=NameOID.LOCALITY_NAME,
                    value=locality,
                )
            )

        subject = issuer = x509.Name(
            attributes=name_parts,
        )

        cert = (
            x509.CertificateBuilder()
            .subject_name(
                name=subject,
            )
            .issuer_name(
                name=issuer,
            )
            .public_key(
                key=private_key.public_key(),
            )
            .serial_number(
                number=uuid.uuid4().int,
            )
            .not_valid_before(
                time=datetime.datetime.now(
                    tz=datetime.timezone.utc,
                ),
            )
            .not_valid_after(
                time=datetime.datetime.now(
                    tz=datetime.timezone.utc,
                )
                + datetime.timedelta(
                    days=validity_days,
                ),
            )
            .add_extension(
                extval=x509.BasicConstraints(
                    ca=True,
                    path_length=None,
                ),
                critical=True,
            )
            .add_extension(
                extval=CAUtils._ca_key_usage(),
                critical=True,
            )
            .sign(
                private_key=private_key,
                algorithm=hashes.SHA256(),
            )
        )

        cert_pem = cert.public_bytes(
            encoding=serialization.Encoding.PEM,
        )
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return cert_pem, key_pem

    @staticmethod
    def _ca_key_usage() -> x509.KeyUsage:
        return x509.KeyUsage(
            digital_signature=True,
            content_commitment=False,
            key_encipherment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False,
        )

    @staticmethod
    def sign_ca(
        cn: str,
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        organization: str = "PyppetDB",
        organizational_unit: str = "CA",
        country: str = "DE",
        state: Optional[str] = "Hessen",
        locality: Optional[str] = None,
        validity_days: int = 3650,
    ) -> Tuple[bytes, bytes]:
        """Generate a CA certificate signed by another CA."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )

        parent_cert = x509.load_pem_x509_certificate(
            data=ca_cert_pem,
        )
        parent_key = serialization.load_pem_private_key(
            data=ca_key_pem,
            password=None,
        )

        name_parts = [
            x509.NameAttribute(
                oid=NameOID.COMMON_NAME,
                value=cn,
            ),
            x509.NameAttribute(
                oid=NameOID.ORGANIZATION_NAME,
                value=organization,
            ),
            x509.NameAttribute(
                oid=NameOID.ORGANIZATIONAL_UNIT_NAME,
                value=organizational_unit,
            ),
            x509.NameAttribute(
                oid=NameOID.COUNTRY_NAME,
                value=country,
            ),
        ]
        if state:
            name_parts.append(
                x509.NameAttribute(
                    oid=NameOID.STATE_OR_PROVINCE_NAME,
                    value=state,
                )
            )
        if locality:
            name_parts.append(
                x509.NameAttribute(
                    oid=NameOID.LOCALITY_NAME,
                    value=locality,
                )
            )

        subject = x509.Name(
            attributes=name_parts,
        )
        issuer = parent_cert.subject

        cert = (
            x509.CertificateBuilder()
            .subject_name(
                name=subject,
            )
            .issuer_name(
                name=issuer,
            )
            .public_key(
                key=private_key.public_key(),
            )
            .serial_number(
                number=uuid.uuid4().int,
            )
            .not_valid_before(
                time=datetime.datetime.now(
                    tz=datetime.timezone.utc,
                ),
            )
            .not_valid_after(
                time=datetime.datetime.now(
                    tz=datetime.timezone.utc,
                )
                + datetime.timedelta(
                    days=validity_days,
                ),
            )
            .add_extension(
                extval=x509.BasicConstraints(
                    ca=True,
                    path_length=None,
                ),
                critical=True,
            )
            .add_extension(
                extval=CAUtils._ca_key_usage(),
                critical=True,
            )
            .sign(
                private_key=parent_key,
                algorithm=hashes.SHA256(),
            )
        )

        cert_pem = cert.public_bytes(
            encoding=serialization.Encoding.PEM,
        )
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return cert_pem, key_pem

    @staticmethod
    def parse_and_extract_csr(
        csr_pem: bytes,
    ) -> Tuple[x509.CertificateSigningRequest, dict]:
        """Parse CSR, verify signature, and extract info."""
        csr = x509.load_pem_x509_csr(
            data=csr_pem,
        )
        if not csr.is_signature_valid:
            raise ValueError("CSR signature is invalid")

        sans = []
        try:
            san_extension = csr.extensions.get_extension_for_class(
                extclass=x509.SubjectAlternativeName,
            )
            sans = [str(name.value) for name in san_extension.value]
        except x509.ExtensionNotFound:
            pass

        info = {
            "cn": csr.subject.get_attributes_for_oid(
                oid=NameOID.COMMON_NAME,
            )[0].value,
            "sans": sans,
        }
        return csr, info

    @staticmethod
    def _build_and_sign_certificate(
        subject: x509.Name,
        public_key: Any,
        extensions: x509.Extensions,
        ca_cert: Union[bytes, x509.Certificate],
        ca_key: Union[bytes, rsa.RSAPrivateKey],
        key_usages: dict[str, bool],
        extended_key_usages: List[str],
        validity_days: int = 365,
        serial_number: Optional[int] = None,
        allowed_extensions: Optional[List[str]] = None,
        injected_sans: Optional[List[str]] = None,
        honor_csr_sans: bool = True,
    ) -> bytes:
        if isinstance(ca_cert, bytes):
            ca_cert = x509.load_pem_x509_certificate(
                data=ca_cert,
            )

        if isinstance(ca_key, bytes):
            ca_key = serialization.load_pem_private_key(
                data=ca_key,
                password=None,
            )

        if serial_number is None:
            serial_number = uuid.uuid4().int

        builder = x509.CertificateBuilder()
        builder = builder.subject_name(
            name=subject,
        )
        builder = builder.issuer_name(
            name=ca_cert.subject,
        )
        builder = builder.public_key(
            key=public_key,
        )
        builder = builder.serial_number(
            number=serial_number,
        )
        builder = builder.not_valid_before(
            time=datetime.datetime.now(
                tz=datetime.timezone.utc,
            ),
        )
        builder = builder.not_valid_after(
            time=datetime.datetime.now(
                tz=datetime.timezone.utc,
            )
            + datetime.timedelta(
                days=validity_days,
            ),
        )
        builder = builder.add_extension(
            extval=x509.BasicConstraints(
                ca=False,
                path_length=None,
            ),
            critical=True,
        )

        builder = builder.add_extension(
            extval=x509.KeyUsage(
                **key_usages,
            ),
            critical=True,
        )

        ekus = []
        for eku in extended_key_usages:
            if hasattr(
                x509.ExtendedKeyUsageOID,
                eku,
            ):
                ekus.append(
                    getattr(
                        x509.ExtendedKeyUsageOID,
                        eku,
                    ),
                )
            else:
                ekus.append(
                    x509.ObjectIdentifier(
                        value=eku,
                    ),
                )
        builder = builder.add_extension(
            extval=x509.ExtendedKeyUsage(
                usages=ekus,
            ),
            critical=False,
        )

        cn = subject.get_attributes_for_oid(
            oid=NameOID.COMMON_NAME,
        )[0].value
        san_extension = None
        try:
            san_extension = extensions.get_extension_for_class(
                extclass=x509.SubjectAlternativeName,
            )
        except x509.ExtensionNotFound:
            pass

        if san_extension and honor_csr_sans:
            dns_names = san_extension.value.get_values_for_type(
                type=x509.DNSName,
            )
            san_values = [
                x509.DNSName(
                    value=name,
                )
                for name in dns_names
            ]
            if cn not in dns_names:
                san_values.append(
                    x509.DNSName(
                        value=str(cn),
                    ),
                )
        else:
            san_values = [
                x509.DNSName(
                    value=str(cn),
                ),
            ]

        if injected_sans:
            existing_dns_names = [
                d.value
                for d in san_values
                if isinstance(
                    d,
                    x509.DNSName,
                )
            ]
            for san in injected_sans:
                if san not in existing_dns_names:
                    san_values.append(
                        x509.DNSName(
                            value=san,
                        ),
                    )
                    existing_dns_names.append(
                        san,
                    )

        builder = builder.add_extension(
            extval=x509.SubjectAlternativeName(
                general_names=san_values,
            ),
            critical=(
                san_extension.critical
                if (san_extension and honor_csr_sans)
                else False
            ),
        )

        if allowed_extensions:
            for extension in extensions:
                if isinstance(
                    extension.value,
                    x509.SubjectAlternativeName,
                ):
                    continue
                oid_str = extension.oid.dotted_string
                if oid_str in allowed_extensions:
                    builder = builder.add_extension(
                        extval=extension.value,
                        critical=extension.critical,
                    )

        cert = builder.sign(
            private_key=ca_key,
            algorithm=hashes.SHA256(),
        )

        return cert.public_bytes(
            encoding=serialization.Encoding.PEM,
        )

    @staticmethod
    def sign_csr(
        csr: Union[bytes, x509.CertificateSigningRequest],
        ca_cert: Union[bytes, x509.Certificate],
        ca_key: Union[bytes, rsa.RSAPrivateKey],
        key_usages: dict[str, bool],
        extended_key_usages: List[str],
        validity_days: int = 365,
        serial_number: Optional[int] = None,
        allowed_extensions: Optional[List[str]] = None,
        injected_sans: Optional[List[str]] = None,
        honor_csr_sans: bool = True,
    ) -> bytes:
        if isinstance(csr, bytes):
            csr = x509.load_pem_x509_csr(
                data=csr.strip(),
            )

        return CAUtils._build_and_sign_certificate(
            subject=csr.subject,
            public_key=csr.public_key(),
            extensions=csr.extensions,
            ca_cert=ca_cert,
            ca_key=ca_key,
            key_usages=key_usages,
            extended_key_usages=extended_key_usages,
            validity_days=validity_days,
            serial_number=serial_number,
            allowed_extensions=allowed_extensions,
            injected_sans=injected_sans,
            honor_csr_sans=honor_csr_sans,
        )

    @staticmethod
    def renew_cert(
        cert: Union[bytes, x509.Certificate],
        ca_cert: Union[bytes, x509.Certificate],
        ca_key: Union[bytes, rsa.RSAPrivateKey],
        key_usages: dict[str, bool],
        extended_key_usages: List[str],
        validity_days: int = 365,
        serial_number: Optional[int] = None,
        allowed_extensions: Optional[List[str]] = None,
        injected_sans: Optional[List[str]] = None,
    ) -> bytes:
        if isinstance(cert, bytes):
            cert = x509.load_pem_x509_certificate(
                data=cert.strip(),
            )

        return CAUtils._build_and_sign_certificate(
            subject=cert.subject,
            public_key=cert.public_key(),
            extensions=cert.extensions,
            ca_cert=ca_cert,
            ca_key=ca_key,
            key_usages=key_usages,
            extended_key_usages=extended_key_usages,
            validity_days=validity_days,
            serial_number=serial_number,
            allowed_extensions=allowed_extensions,
            injected_sans=injected_sans,
        )

    @staticmethod
    def get_cert_info(cert_pem: bytes) -> dict:
        """Extract information from a certificate."""
        cert = x509.load_pem_x509_certificate(
            data=cert_pem,
        )

        sans = []
        try:
            san_extension = cert.extensions.get_extension_for_class(
                extclass=x509.SubjectAlternativeName,
            )
            sans = [str(name.value) for name in san_extension.value]
        except x509.ExtensionNotFound:
            pass

        return {
            "cn": cert.subject.get_attributes_for_oid(
                oid=NameOID.COMMON_NAME,
            )[0].value,
            "issuer": cert.issuer.rfc4514_string(),
            "serial_number": str(cert.serial_number),
            "not_before": cert.not_valid_before_utc,
            "not_after": cert.not_valid_after_utc,
            "fingerprint": {
                "sha256": cert.fingerprint(
                    algorithm=hashes.SHA256(),
                ).hex(),
                "sha1": cert.fingerprint(
                    algorithm=hashes.SHA1(),
                ).hex(),
                "md5": cert.fingerprint(
                    algorithm=hashes.MD5(),
                ).hex(),
            },
            "sans": sans,
        }

    @staticmethod
    def generate_crl(
        ca_cert: Union[bytes, x509.Certificate],
        ca_key: Union[bytes, rsa.RSAPrivateKey],
        revoked_certs: List[dict],
        validity_days: int = 30,
    ) -> Tuple[bytes, datetime.datetime]:
        """Generate a Certificate Revocation List (CRL)."""
        if isinstance(ca_cert, bytes):
            ca_cert = x509.load_pem_x509_certificate(
                data=ca_cert,
            )

        if isinstance(ca_key, bytes):
            ca_key = serialization.load_pem_private_key(
                data=ca_key,
                password=None,
            )

        last_update = datetime.datetime.now(
            tz=datetime.timezone.utc,
        )
        next_update = last_update + datetime.timedelta(
            days=validity_days,
        )

        builder = x509.CertificateRevocationListBuilder()
        builder = builder.issuer_name(
            issuer_name=ca_cert.subject,
        )
        builder = builder.last_update(
            last_update=last_update,
        )
        builder = builder.next_update(
            next_update=next_update,
        )

        for cert in revoked_certs:
            revoked_cert = (
                x509.RevokedCertificateBuilder()
                .serial_number(
                    number=cert["serial_number"],
                )
                .revocation_date(
                    time=cert["revocation_date"],
                )
                .build()
            )
            builder = builder.add_revoked_certificate(
                revoked_certificate=revoked_cert,
            )

        crl = builder.sign(
            private_key=ca_key,
            algorithm=hashes.SHA256(),
        )
        return (
            crl.public_bytes(
                encoding=serialization.Encoding.PEM,
            ),
            next_update,
        )
