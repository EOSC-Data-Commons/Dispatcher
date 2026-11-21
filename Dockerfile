FROM python:3.13

RUN groupadd -r celery && useradd -r -g celery celery
WORKDIR /usr/src

# Set environment variables
# Prevents Python from writing pyc files to disk
ENV PYTHONDONTWRITEBYTECODE=1
#Prevents Python from buffering stdout and stderr
ENV PYTHONUNBUFFERED=1

# Install uv from the official image (pinned for reproducibility)
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

# Copy requirements first so dependency installation is cached separately
# from the application code.
COPY requirements.txt /usr/src

# Install dependencies (vre-rocrate from the github URL in requirements.txt).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

COPY . /usr/src

# If vre-rocrate/ was copied into the build context (e.g. by the source_local
# ansible role), override the github install with the local editable install.
RUN if [ -d "/usr/src/vre-rocrate" ]; then \
    uv pip install --system --no-deps -e /usr/src/vre-rocrate; \
    fi
