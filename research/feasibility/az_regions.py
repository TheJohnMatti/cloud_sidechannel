"""AWS availability-zone global-ID prefix -> region name.

Pauley's dataset uses global AZ IDs (`use1-az1`); ISI uses AZ names (`us-east-1a`).
This maps the ID prefix (everything before `-az`) to the region.
Source: AWS docs (AZ IDs) + Resource Access Manager region list. Majors are what
matter for the analysis; unknowns fall through to the raw prefix.
"""

AZID_PREFIX_TO_REGION = {
    "use1": "us-east-1", "use2": "us-east-2",
    "usw1": "us-west-1", "usw2": "us-west-2",
    "cac1": "ca-central-1", "caw1": "ca-west-1",
    "euw1": "eu-west-1", "euw2": "eu-west-2", "euw3": "eu-west-3",
    "euc1": "eu-central-1", "euc2": "eu-central-2",
    "eun1": "eu-north-1", "eus1": "eu-south-1", "eus2": "eu-south-2",
    "apne1": "ap-northeast-1", "apne2": "ap-northeast-2", "apne3": "ap-northeast-3",
    "apse1": "ap-southeast-1", "apse2": "ap-southeast-2", "apse3": "ap-southeast-3",
    "apse4": "ap-southeast-4", "apse5": "ap-southeast-5", "apse7": "ap-southeast-7",
    "aps1": "ap-south-1", "aps2": "ap-south-2",
    "ape1": "ap-east-1", "ape2": "ap-east-2",
    "sae1": "sa-east-1",
    "afs1": "af-south-1",
    "mes1": "me-south-1", "mec1": "me-central-1",
    "ilc1": "il-central-1",
    "mxc1": "mx-central-1",
    "use1-bos1": "us-east-1", "use1-chi1": "us-east-1", "use1-dfw1": "us-east-1",
    "use1-iah1": "us-east-1", "use1-mci1": "us-east-1", "use1-msp1": "us-east-1",
    "use1-nyc1": "us-east-1", "use1-phl1": "us-east-1", "use1-atl1": "us-east-1",
}


def azid_to_region(az_id: str) -> str:
    """`use1-az1` -> `us-east-1`. Local Zones (`use1-bos1-az1`) fold to the parent."""
    parts = az_id.split("-")
    # standard: <prefix>-az<n>  ->  prefix is parts[0]
    prefix = parts[0]
    if prefix in AZID_PREFIX_TO_REGION:
        return AZID_PREFIX_TO_REGION[prefix]
    # local/wavelength zones: <prefix>-<city><n>-az<n>
    two = "-".join(parts[:2])
    if two in AZID_PREFIX_TO_REGION:
        return AZID_PREFIX_TO_REGION[two]
    return prefix  # unknown — keep raw so it's visible, not silently merged
