# Dispatcher

A **WORK-IN-PROGRESS** prototype of EDC Dispatcher, see also [Dispatcher page](https://confluence.egi.eu/display/EOSCDATACOMMONS/Dispatcher+draft) in project Confluence.

**Note:** This is a proof-of-concept implementation and should not be used in production without further testing and refinement.

## Overview

Dispatcher is a component which consumes a ROCrate object (either ZIP file or just its `ro-crate-metadata.json`) containing references to workflow and its input files, 
and instantiates an environment for the user, where the data are available and the workflow can be started.

The ROCrate profile Dispatcher recognizes is not fully defined yet, follow examples in [test/](test/).

The endpoint accepts requests at the paths:
- `/requests/zip_rocrate`: POST, ROCrate as a zip file in the body
- `/requests/metadata_rocrate`: POST, only the `ro-crate-metatada.json` in the body

On successful completition, a URL pointing to the prepared environment is returned.

**Current restrictions:**
- Jupiter/Binder is temporarily broken (not fully integrated in the refactored version)


## Deployment

To deploy your own Dispatcher instance you need:

1. Prepare a clean Ubuntu machine (VM) with public ip, DNS name `DISPATCHER_HOSTNAME` and at least ports 22, 80, and 443 open, and make sure (install public key etc) `ssh ubuntu@DISPATCHER_HOSTNAME` works from your current environment.
2. Register `DISPATCHER_HOSTNAME` as a service provider with EGI Checkin (development instance):
   - Go to https://aai.egi.eu/federation/egi/services/ and log in
   - Click on `New service`, choose `Development` for `Integration Environment`, and fill in the few mandatory fields
   - Click on `Protocol specific` and choose `OIDC Service`; keep the defautl values except the following
   - Provide two `Redirect URI` values:
       - `https://DISPATCHER_HOSTNAME/oauth2/egi-checkin/token`
       - `https://DISPATCHER_HOSTNAME/docs/oauth2-redirect`
   - Keep `PKCE will not be used` despite of the warning
   - Enable refresh tokens
   - Submit the form and self-approve it (one can do so in the development environment)
5. Create Ansible vault in `ansible/host_vars/DISPATCHER_HOSTNAME/secrets.yml` (protected with a password stored in `ansible/.vault-password.txt`) and fill it with values grabbed from the service registration form:
```
oauth2:
  client_id: "YOUR-CLIENT-ID"
  client_secret: "YOUR-CLIENT-SECRET"
```
8. Add DISPATCHER_HOSTNAME server's domain defined in `ansible/hosts.yml` among `dispatcher.hosts`
9. `cd ansible`
10. `ansible-playbook dispatcher.yml`


## Example API Calls

Go to https://DISPATCHER_HOSTNAME/oauth2/login, which will redirect you to EGI CheckIn for the login sequence.
Then it lands back to https://DISPATCHER_HOSTNAME/docs, where API calls are available

### Galaxy

Going to https://usegalaxy.eu/,
Dispatcher creates a landing page with simple workflow, that accepts a `txt` file and creates its reversed copy.

1. `POST /requests/metadata_rocrate`. Use [test/galaxy/ro-crate-metadata.json](test/galaxy/ro-crate-metadata.json) as payload.
2. `GET /requests/REQUEST-UUID` to retrieve the target URL to execute the workflow. The UUID is returned by the POST request above

### Simple Binder

Trivial Jupyter notebook (print the Pi value). 
The test talks to our Binder service; it would be better to use https://mybinder.org/ but it blocks communication to non-standard ports,
which we use for testing typically.
Change `#destination` in `ro-crate-metadata.json` eventually.

Zip the content of [test/simple-binder](test/simple-binder) and post the file to `/requests/zip_rocrate/`

### More realistict Binder

Testing notebook stolen from our other project, which takls to our service to find similar AlphaFold protein structures and displays their alignment.

Again, zip [test/alphafind-notebook](test/alphafind-notebook) and post the file to `/requests/zip_rocrate/`


## Obsolete

Probably broken, old stuff

To run Dispatcher, follow these steps:

1. Clone this repository: `git clone https://github.com/EOSC-Data-Commons/Dispatcher.git`
2. Build the Docker image: `docker build -t dispatcher .`
3. Run the Docker container: `docker run -d -p 8000:8000 dispatcher`

This will start the API server on `localhost:8000`.

Alternatively, a Python virtual environment can be created, dependencies installed from [requirements.txt](requirements.txt), and the server started with:
```
uvicorn app.main:app --port 8000
```
