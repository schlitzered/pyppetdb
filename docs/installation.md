# Installation

## Prerequisites

pyppetdb is strictly tested on **Python 3.12**. While it may run on other versions, all
dependencies in `requirements.txt` are verified against the 3.12 runtime. It is highly
recommended to run pyppetdb within a dedicated virtual environment.

### System Dependencies

pyppetdb utilizes the `bonsai` library for optional LDAP integration (used to synchronize
teams with LDAP group members). To install this dependency, your system must have LDAP
development headers and a C compiler installed.

**On Debian/Ubuntu:**
```bash
sudo apt-get install build-essential python3.12-dev libldap2-dev libsasl2-dev
```

**On RHEL/CentOS:**
```bash
sudo yum install gcc python3.12-devel openldap-devel cyrus-sasl-devel
```

## Recommended Setup

1.  **Create a Virtual Environment:**
    ```bash
    python3.12 -m venv /opt/pyppetdb
    source /opt/pyppetdb/bin/activate
    ```

2.  **Install pyppetdb:**
    You can install pyppetdb directly via pip:
    ```bash
    pip install pyppetdb
    ```

3.  **Install from Source (Development):**
    If you are installing from the repository:
    ```bash
    git clone https://github.com/schlitzered/pyppetdb.git
    cd pyppetdb
    pip install -r requirements.txt
    ```
