"""What the suite owns on the box. Every instance and shared folder it
creates is named gt<6 hex>, optionally followed by a suffix letter."""

import re

TEST_NAME = re.compile(r"gt[0-9a-f]{6}")


def is_test_name(name: str) -> bool:
    return TEST_NAME.match(name) is not None
