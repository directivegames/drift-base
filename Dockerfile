ARG PYTHON_VERSION=3.11.8
ARG BASE_IMAGE=bullseye

FROM python:${PYTHON_VERSION}-slim-${BASE_IMAGE} AS builder

RUN set -ex \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

ENV PYTHONUSERBASE=/root/.app

RUN python -m pip install --upgrade pip
RUN pip install poetry
RUN pip install --user --ignore-installed --no-warn-script-location gunicorn

COPY pyproject.toml poetry.lock ./

# The credentials for pip/pipenv are supplied via a Docker secret which we mount and source so that commands
# can access them as environment variables.

# Pipenv will ignore qualifying system packages during install, so we need to route through pip to ensure everything
# really ends up in our /root/.local folder where we want it to be
RUN --mount=type=secret,id=pip-credentials \
    export $(grep -v '^#' /run/secrets/pip-credentials | xargs) \
    && poetry export --without dev --without-hashes -o requirements.in.txt

# Once we have our requirements.txt, we install everything the user folder defined above with PYTHONUSERBASE
RUN --mount=type=secret,id=pip-credentials --mount=type=cache,target=/root/.cache \
    export $(grep -v '^#' /run/secrets/pip-credentials | xargs) \
    && sed -e 's!https://nexus!https://\${PYPI_USERNAME}:\${PYPI_PASSWORD}@nexus!' -e 's/--extra-index-url/-i/' requirements.in.txt >requirements.txt \
    && pip install --user --ignore-installed --no-warn-script-location -r requirements.txt

FROM python:${PYTHON_VERSION}-slim-${BASE_IMAGE} AS app
LABEL Maintainer="Directive Games <info@directivegames.com>"

ENV PYTHONUNBUFFERED=1

RUN set -ex \
    && addgroup --gid 1000 gunicorn && useradd -ms /bin/bash gunicorn -g gunicorn \
    && apt-get update \
    && apt-get upgrade -y \
    && apt-get autoremove -y \
    && apt-get clean -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --chown=gunicorn:gunicorn --from=builder /root/.app/ /home/gunicorn/.local/
COPY . .

ARG VERSION
ARG BUILD_TIMESTAMP
ARG COMMIT_SHA
ARG GIT_REPO_URL

LABEL AppVersion="${VERSION}"
LABEL CommitHash="${COMMIT_SHA}"

ENV DD_GIT_REPOSITORY_URL=${GIT_REPO_URL}
ENV DD_GIT_COMMIT_SHA=${COMMIT_SHA}

# For runtime consumption
RUN echo '{"version": "'${VERSION}'", "build_timestamp": "'${BUILD_TIMESTAMP}'", "commit_hash": "'${COMMIT_SHA}'"}' > .build_info

USER gunicorn

ENV PATH=/home/gunicorn/.local/bin:$PATH

CMD ["gunicorn", "--config", "./config/gunicorn.conf.py"]
