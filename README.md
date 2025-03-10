[![Build Status](https://github.com/directivegames/drift-base/workflows/Build%20and%20Test/badge.svg)](https://github.com/directivegames/drift-base)
[![codecov](https://codecov.io/gh/directivegames/drift-base/branch/develop/graph/badge.svg)](https://codecov.io/gh/directivegames/drift-base)


# drift-base
Base Services for Drift micro-framework.

## Installation:
Run the following commands to install this project in developer mode:

```bash
pipx install poetry
pipx inject poetry poetry-plugin-export
pipx inject poetry poetry-plugin-shell
poetry install --sync --no-root
```

Run the following commands to enable drift and drift-config in developer mode for this project:

```bash
poetry shell  # Make sure the virtualenv is active

pip install -e "../drift[aws,test]"
pip install -e "../drift-config[s3-backend,redis-backend]"
```

## Run localserver
This starts a server on port 10080:

```bash
poetry shell  # Make sure the virtualenv is active

make run-flask
```

Try it out here:
[http://localhost:10080/](http://localhost:5000/)


## Running Tests
1. Launch the backend
2. Add pycharm test config
3. (Windows only) Install atomicwrites

The backend needs to be up and running in order to run the tests successfully.
Run the following command from WSL from the project root to get postgres & redis up and running:

```bash
poetry shell  # Make sure the virtualenv is active

make run-backend
```

Tests that are run need to have the following environment variable set in the pycharm run/debug config:

```bash
DRIFT_APP_ROOT=C:\path_to\project_root  # replace with proper path
```

If on Windows, then you might also need to install the atomicwrites package for the python interperater used by the environment.


## Modifying library dependencies
Python package dependencies are maintained in **pyproject.toml**. If you make any changes there, update the **poetry.lock** file as well using the following command:

```bash
poetry lock
```

## Working with AWS

Note! For any of the following commands to work, make sure the virtualenv is active and the proper configuration database and tier is selected:

```bash
poetry shell
export DRIFT_CONFIG_URL=somecfg && export DRIFT_TIER=SOME_NAME
```

### Building drift-base
Drift-base runs in docker. To build and push a docker image run the following:
```bash
make build
make push
```

This will create a docker image called `directivegames/drift-base:<branch-name>` and push it to dockerhub here: https://hub.docker.com/repository/docker/directivegames/drift-base/tags?page=1

You can run the container locally with the following command:
```bash
make run
```
Note that you must have the following environment variables set up: `DRIFT_TIER` and `DRIFT_CONFIG_URL`. See example.env.

drift-base docker images are automatically built by GutHub Actions on all branches and tagged by the branch name. If any git tag is pushed, a docker image will be built with that tag as well.

Versioned images are created in this way. Simply add a version tag to git and an image with correct version will be built. Any image built after this version tag push will export the same version in its root endpoint.

Note that new tags should only be created on the master branch, or a support/M.m branch for previous Major.minor support versions.

To create a new version of drift-base run:
```bash
git tag 1.2.3
git push --tags
```
