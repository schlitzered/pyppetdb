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
from typing import Tuple, Optional, List, Union
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
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
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit),
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        ]
        if state:
            name_parts.append(x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state))
        if locality:
            name_parts.append(x509.NameAttribute(NameOID.LOCALITY_NAME, locality))

        builder = x509.CertificateSigningRequestBuilder()
        builder = builder.subject_name(x509.Name(name_parts))

        if alt_names:
            san = x509.SubjectAlternativeName(
                [x509.DNSName(name) for name in alt_names]
            )
            builder = builder.add_extension(san, critical=False)

        csr = builder.sign(private_key, hashes.SHA256())

        csr_pem = csr.public_bytes(serialization.Encoding.PEM)
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
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit),
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        ]
        if state:
            name_parts.append(x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state))
        if locality:
            name_parts.append(x509.NameAttribute(NameOID.LOCALITY_NAME, locality))

        subject = issuer = x509.Name(name_parts)

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(uuid.uuid4().int)
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=validity_days)
            )
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(private_key, hashes.SHA256())
        )

        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return cert_pem, key_pem

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

        parent_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        parent_key = serialization.load_pem_private_key(ca_key_pem, password=None)

        name_parts = [
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, organizational_unit),
            x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        ]
        if state:
            name_parts.append(x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, state))
        if locality:
            name_parts.append(x509.NameAttribute(NameOID.LOCALITY_NAME, locality))

        subject = x509.Name(name_parts)
        issuer = parent_cert.subject

        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(uuid.uuid4().int)
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=validity_days)
            )
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .sign(parent_key, hashes.SHA256())
        )

        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return cert_pem, key_pem

    @staticmethod
    def verify_csr_signature(csr_pem: bytes) -> bool:
        """Verify the signature of a CSR."""
        csr = x509.load_pem_x509_csr(csr_pem)
        return csr.is_signature_valid

    @staticmethod
    def sign_csr(
        csr_pem: bytes,
        ca_cert: Union[bytes, x509.Certificate],
        ca_key: Union[bytes, rsa.RSAPrivateKey],
        validity_days: int = 365,
        serial_number: Optional[int] = None,
        key_usages: Optional[List[str]] = None,
        extended_key_usages: Optional[List[str]] = None,
        allowed_extensions: Optional[List[str]] = None,
        injected_sans: Optional[List[str]] = None,
    ) -> bytes:
        """Sign a CSR with the CA certificate and key."""
        csr = x509.load_pem_x509_csr(csr_pem)

        if isinstance(ca_cert, bytes):
            ca_cert = x509.load_pem_x509_certificate(ca_cert)

        if isinstance(ca_key, bytes):
            ca_key = serialization.load_pem_private_key(ca_key, password=None)

        if serial_number is None:
            serial_number = uuid.uuid4().int

        builder = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(serial_number)
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=validity_days)
            )
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
        )

        # Add Key Usage if provided
        if key_usages:
            usage_kwargs = {
                "digital_signature": False,
                "content_commitment": False,
                "key_encipherment": False,
                "data_encipherment": False,
                "key_agreement": False,
                "key_cert_sign": False,
                "crl_sign": False,
                "encipher_only": False,
                "decipher_only": False,
            }
            for usage in key_usages:
                if usage in usage_kwargs:
                    usage_kwargs[usage] = True

            builder = builder.add_extension(
                x509.KeyUsage(**usage_kwargs),
                critical=True,
            )
        else:
            # Default fallback
            builder = builder.add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )

        # Add Extended Key Usage if provided
        if extended_key_usages:
            ekus = []
            for eku in extended_key_usages:
                if hasattr(x509.ExtendedKeyUsageOID, eku):
                    ekus.append(getattr(x509.ExtendedKeyUsageOID, eku))
                else:
                    ekus.append(x509.ObjectIdentifier(eku))
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(ekus),
                critical=False,
            )
        else:
            # Default fallback
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(
                    [
                        x509.ExtendedKeyUsageOID.SERVER_AUTH,
                        x509.ExtendedKeyUsageOID.CLIENT_AUTH,
                    ]
                ),
                critical=False,
            )

        cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        san_extension = None
        try:
            san_extension = csr.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
        except x509.ExtensionNotFound:
            pass

        san_values = []
        if san_extension:
            san_values = list(san_extension.value)
            dns_names = san_extension.value.get_values_for_type(x509.DNSName)
            if cn not in dns_names:
                san_values.append(x509.DNSName(cn))
        else:
            san_values = [x509.DNSName(cn)]

        if injected_sans:
            existing_dns_names = [
                d.value for d in san_values if isinstance(d, x509.DNSName)
            ]
            for san in injected_sans:
                if san not in existing_dns_names:
                    san_values.append(x509.DNSName(san))
                    existing_dns_names.append(san)

        builder = builder.add_extension(
            x509.SubjectAlternativeName(san_values),
            critical=san_extension.critical if san_extension else False,
        )

        if allowed_extensions:
            for extension in csr.extensions:
                if isinstance(extension.value, x509.SubjectAlternativeName):
                    continue
                # Check if OID or Name is in allowed list
                oid_str = extension.oid.dotted_string
                # We could also check names but OID is safer
                if oid_str in allowed_extensions:
                    builder = builder.add_extension(
                        extension.value, critical=extension.critical
                    )

        cert = builder.sign(ca_key, hashes.SHA256())

        return cert.public_bytes(serialization.Encoding.PEM)

    @staticmethod
    def renew_cert(
        cert_pem: bytes,
        ca_cert: Union[bytes, x509.Certificate],
        ca_key: Union[bytes, rsa.RSAPrivateKey],
        validity_days: int = 365,
        serial_number: Optional[int] = None,
        key_usages: Optional[List[str]] = None,
        extended_key_usages: Optional[List[str]] = None,
        allowed_extensions: Optional[List[str]] = None,
        injected_sans: Optional[List[str]] = None,
    ) -> bytes:
        """Renew a certificate with the CA certificate and key."""
        old_cert = x509.load_pem_x509_certificate(cert_pem)

        if isinstance(ca_cert, bytes):
            ca_cert = x509.load_pem_x509_certificate(ca_cert)

        if isinstance(ca_key, bytes):
            ca_key = serialization.load_pem_private_key(ca_key, password=None)

        if serial_number is None:
            serial_number = uuid.uuid4().int

        builder = (
            x509.CertificateBuilder()
            .subject_name(old_cert.subject)
            .issuer_name(ca_cert.subject)
            .public_key(old_cert.public_key())
            .serial_number(serial_number)
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=validity_days)
            )
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
        )

        # Add Key Usage if provided
        if key_usages:
            usage_kwargs = {
                "digital_signature": False,
                "content_commitment": False,
                "key_encipherment": False,
                "data_encipherment": False,
                "key_agreement": False,
                "key_cert_sign": False,
                "crl_sign": False,
                "encipher_only": False,
                "decipher_only": False,
            }
            for usage in key_usages:
                if usage in usage_kwargs:
                    usage_kwargs[usage] = True

            builder = builder.add_extension(
                x509.KeyUsage(**usage_kwargs),
                critical=True,
            )
        else:
            # Default fallback
            builder = builder.add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )

        # Add Extended Key Usage if provided
        if extended_key_usages:
            ekus = []
            for eku in extended_key_usages:
                if hasattr(x509.ExtendedKeyUsageOID, eku):
                    ekus.append(getattr(x509.ExtendedKeyUsageOID, eku))
                else:
                    ekus.append(x509.ObjectIdentifier(eku))
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(ekus),
                critical=False,
            )
        else:
            # Default fallback
            builder = builder.add_extension(
                x509.ExtendedKeyUsage(
                    [
                        x509.ExtendedKeyUsageOID.SERVER_AUTH,
                        x509.ExtendedKeyUsageOID.CLIENT_AUTH,
                    ]
                ),
                critical=False,
            )

        cn = old_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        san_extension = None
        try:
            san_extension = old_cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
        except x509.ExtensionNotFound:
            pass

        san_values = []
        if san_extension:
            san_values = list(san_extension.value)
            dns_names = san_extension.value.get_values_for_type(x509.DNSName)
            if cn not in dns_names:
                san_values.append(x509.DNSName(cn))
        else:
            san_values = [x509.DNSName(cn)]

        if injected_sans:
            existing_dns_names = [
                d.value for d in san_values if isinstance(d, x509.DNSName)
            ]
            for san in injected_sans:
                if san not in existing_dns_names:
                    san_values.append(x509.DNSName(san))
                    existing_dns_names.append(san)

        builder = builder.add_extension(
            x509.SubjectAlternativeName(san_values),
            critical=san_extension.critical if san_extension else False,
        )

        if allowed_extensions:
            for extension in old_cert.extensions:
                if isinstance(extension.value, x509.SubjectAlternativeName):
                    continue
                # Check if OID or Name is in allowed list
                oid_str = extension.oid.dotted_string
                if oid_str in allowed_extensions:
                    builder = builder.add_extension(
                        extension.value, critical=extension.critical
                    )

        new_cert = builder.sign(ca_key, hashes.SHA256())

        return new_cert.public_bytes(serialization.Encoding.PEM)

    @staticmethod
    def get_csr_info(csr_pem: bytes) -> dict:
        """Extract information from a CSR."""
        csr = x509.load_pem_x509_csr(csr_pem)

        sans = []
        try:
            san_extension = csr.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            sans = [str(name.value) for name in san_extension.value]
        except x509.ExtensionNotFound:
            pass

        return {
            "cn": csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
            "sans": sans,
        }

    @staticmethod
    def get_cert_info(cert_pem: bytes) -> dict:
        """Extract information from a certificate."""
        cert = x509.load_pem_x509_certificate(cert_pem)

        sans = []
        try:
            san_extension = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            )
            sans = [str(name.value) for name in san_extension.value]
        except x509.ExtensionNotFound:
            pass

        return {
            "cn": cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
            "issuer": cert.issuer.rfc4514_string(),
            "serial_number": str(cert.serial_number),
            "not_before": cert.not_valid_before_utc,
            "not_after": cert.not_valid_after_utc,
            "fingerprint": {
                "sha256": cert.fingerprint(hashes.SHA256()).hex(),
                "sha1": cert.fingerprint(hashes.SHA1()).hex(),
                "md5": cert.fingerprint(hashes.MD5()).hex(),
            },
            "sans": sans,
        }

    @staticmethod
    def generate_crl(
        ca_cert: Union[bytes, x509.Certificate],
        ca_key: Union[bytes, rsa.RSAPrivateKey],
        revoked_certs: List[
            dict
        ],  # List of {"serial_number": int, "revocation_date": datetime}
        validity_days: int = 30,
    ) -> Tuple[bytes, datetime.datetime]:
        """Generate a Certificate Revocation List (CRL)."""
        if isinstance(ca_cert, bytes):
            ca_cert = x509.load_pem_x509_certificate(ca_cert)

        if isinstance(ca_key, bytes):
            ca_key = serialization.load_pem_private_key(ca_key, password=None)

        last_update = datetime.datetime.now(datetime.timezone.utc)
        next_update = last_update + datetime.timedelta(days=validity_days)

        builder = x509.CertificateRevocationListBuilder()
        builder = builder.issuer_name(ca_cert.subject)
        builder = builder.last_update(last_update)
        builder = builder.next_update(next_update)

        for cert in revoked_certs:
            revoked_cert = (
                x509.RevokedCertificateBuilder()
                .serial_number(cert["serial_number"])
                .revocation_date(cert["revocation_date"])
                .build()
            )
            builder = builder.add_revoked_certificate(revoked_cert)

        crl = builder.sign(ca_key, hashes.SHA256())
        return crl.public_bytes(serialization.Encoding.PEM), next_update
