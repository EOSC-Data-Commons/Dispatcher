FROM python:3.13

# Non-root service user (v4 D6 token hygiene: the SQLite registry/credential
# file is 600/700 and must not be root-readable). /data is the DB volume
# mountpoint — docker copies its ownership into a fresh named volume.
RUN groupadd -r dispatcher && useradd -r -g dispatcher dispatcher \
    && mkdir -p /data && chown dispatcher:dispatcher /data
WORKDIR /usr/src

# Set environment variables
# Prevents Python from writing pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
#Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Upgrade pip
RUN pip install --upgrade pip

# Copy requirements and dispatcher code (vre-rocrate is optional for local builds)
COPY requirements.txt /usr/src
COPY . /usr/src

# Install dependencies.
# If vre-rocrate/ directory was copied into the build context (e.g. by source_local role),
# install it from there. Otherwise install from the github URL in requirements.txt.
RUN if [ -d "/usr/src/vre-rocrate" ]; then \
    pip install --no-cache-dir -e /usr/src/vre-rocrate && \
    grep -v "vre-rocrate" requirements.txt > /tmp/requirements-no-vre.txt && \
    pip install --no-cache-dir -r /tmp/requirements-no-vre.txt; \
    else \
    pip install --no-cache-dir -r requirements.txt; \
    fi

USER dispatcher
