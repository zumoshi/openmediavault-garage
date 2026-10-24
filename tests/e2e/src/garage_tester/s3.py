"""S3 smoke via boto3 against the instance's S3 port."""

import hashlib
import os

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError


def client(endpoint: str, key_id: str, secret: str):
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="garage",
        config=Config(s3={"addressing_style": "path"}),
    )


def round_trip(endpoint: str, key_id: str, secret: str,
               bucket: str, payload: bytes):
    s3 = client(endpoint, key_id, secret)
    s3.put_object(Bucket=bucket, Key="tester.txt", Body=payload)
    got = s3.get_object(Bucket=bucket, Key="tester.txt")["Body"].read()
    assert got == payload, "S3 round trip content mismatch"


def must_be_denied(endpoint: str, key_id: str = "GKinvalid",
                   secret: str = "invalid") -> None:
    """Invalid credentials must never list buckets."""
    try:
        client(endpoint, key_id, secret).list_buckets()
    except ClientError:
        return
    raise AssertionError("invalid S3 credentials were accepted")


def put_random_objects(s3, bucket: str, count: int,
                       size: int) -> dict[str, str]:
    """Put `count` objects of `size` random bytes. Returns each key's
    sha256."""
    digests = {}
    for i in range(count):
        body = os.urandom(size)
        key = f"obj-{i:04d}"
        s3.put_object(Bucket=bucket, Key=key, Body=body)
        digests[key] = hashlib.sha256(body).hexdigest()
    return digests


def unreadable(s3, bucket: str, digests: dict[str, str]) -> dict[str, str]:
    """The objects that do not read back with their sha256, and why.
    Garage may send the headers and then cut the body, so this reads the
    whole body."""
    failed = {}
    for key, digest in digests.items():
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as e:  # any failure to read counts, keep its type
            failed[key] = f"{type(e).__name__}: {e}"
            continue
        if hashlib.sha256(body).hexdigest() != digest:
            failed[key] = f"content differs ({len(body)} bytes read)"
    return failed
