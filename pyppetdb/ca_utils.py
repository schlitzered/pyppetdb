import datetime
import uuid
from typing import Tuple, Optional, List
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

class CAUtils:
    @staticmethod
    def generate_ca(
        common_name: str,
        organization: str = "PyppetDB",
        organizational_unit: str = "CA",
        country: str = "US",
        state: Optional[str] = None,
        locality: Optional[str] = None,
        validity_days: int = 3650
    ) -> Tuple[bytes, bytes]:
        """Generate a self-signed CA certificate and private key."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
        
        name_parts = [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
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
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=validity_days)
            )
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None), critical=True,
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
        common_name: str,
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        organization: str = "PyppetDB",
        organizational_unit: str = "CA",
        country: str = "US",
        state: Optional[str] = None,
        locality: Optional[str] = None,
        validity_days: int = 3650
    ) -> Tuple[bytes, bytes]:
        """Generate a CA certificate signed by another CA."""
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
        
        parent_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        parent_key = serialization.load_pem_private_key(ca_key_pem, password=None)
        
        name_parts = [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
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
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=validity_days)
            )
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None), critical=True,
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
    def sign_csr(
        csr_pem: bytes,
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        validity_days: int = 365
    ) -> bytes:
        """Sign a CSR with the CA certificate and key."""
        csr = x509.load_pem_x509_csr(csr_pem)
        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
        
        cert = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(ca_cert.subject)
            .public_key(csr.public_key())
            .serial_number(uuid.uuid4().int)
            .not_valid_before(datetime.datetime.now(datetime.timezone.utc))
            .not_valid_after(
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=validity_days)
            )
            .sign(ca_key, hashes.SHA256())
        )
        
        return cert.public_bytes(serialization.Encoding.PEM)

    @staticmethod
    def get_cert_info(cert_pem: bytes) -> dict:
        """Extract information from a certificate."""
        cert = x509.load_pem_x509_certificate(cert_pem)
        return {
            "common_name": cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value,
            "issuer": cert.issuer.rfc4514_string(),
            "serial_number": str(cert.serial_number),
            "not_before": cert.not_valid_before_utc,
            "not_after": cert.not_valid_after_utc,
            "fingerprint": {
                "sha256": cert.fingerprint(hashes.SHA256()).hex(),
                "sha1": cert.fingerprint(hashes.SHA1()).hex(),
                "md5": cert.fingerprint(hashes.MD5()).hex(),
            },
        }

    @staticmethod
    def generate_crl(
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        revoked_certs: List[dict]  # List of {"serial_number": int, "revocation_date": datetime}
    ) -> bytes:
        """Generate a Certificate Revocation List (CRL)."""
        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
        
        builder = x509.CertificateRevocationListBuilder()
        builder = builder.issuer_name(ca_cert.subject)
        builder = builder.last_update(datetime.datetime.now(datetime.timezone.utc))
        builder = builder.next_update(
            datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
        )
        
        for cert in revoked_certs:
            revoked_cert = (
                x509.RevokedCertificateBuilder()
                .serial_number(cert["serial_number"])
                .revocation_date(cert["revocation_date"])
                .build()
            )
            builder = builder.add_revoked_certificate(revoked_cert)
            
        crl = builder.sign(ca_key, hashes.SHA256())
        return crl.public_bytes(serialization.Encoding.PEM)
