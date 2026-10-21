"""S3 smoke via boto3 against the instance's S3 port."""

import boto3
from botocore.client import Config


def round_trip(host: str, port: int, key_id: str, secret: str,
               bucket: str, payload: bytes):
    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{host}:{port}",
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
        region_name="garage",
        config=Config(s3={"addressing_style": "path"}),
    )
    s3.put_object(Bucket=bucket, Key="tester.txt", Body=payload)
    got = s3.get_object(Bucket=bucket, Key="tester.txt")["Body"].read()
    assert got == payload, "S3 round trip content mismatch"
