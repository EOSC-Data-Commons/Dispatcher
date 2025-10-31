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

## Quickstart

We do our best to keep [development instance](https://dev1.player.eosc-data-commons.eu/docs) running the current version, and it is available for testing.
Report if anything is broken, please.

1. Go to https://dev1.player.eosc-data-commons.eu; this should redirect you to EGI CheckIn identity provider
2. You will be redirected to /docs; this is an automatically generated Swagger UI page capable of making test calls
3. Choose an example in  [test/](test/) (refer to brief description below):
   - grab `ro-crate-metadata.json` if it is the only file of the example
   - make a flat zip file containing all the files of the example otherwise
4. POST the file via the Swagger to `/requests/metadata_rocrate` or `/requests/zip_rocrate`. The server returns `request_id`
5. GET `/requests/YOUR_REQUEST_ID` repeatedly to monitor processing of the request
6. If everythings goes right, `SUCCESS` status is returned finally, containing the endpoint to the target VRE
7. If anything goes wrong, check you are still authenticated by calling GET /oauth2/token. If you don't see the token, follow step 1.

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

### Galaxy TOSCA
Similar to Galaxy but it goes via [Infrastructure Manager](https://www.grycap.upv.es/im/index.php) to set up a private Galaxy instance.
Highly experimental so far.

### Scipion TOSCA
Deploy [Scipion](https://scipion.i2pc.es/) cryo EM data processing package via  [Infrastructure Manager](https://www.grycap.upv.es/im/index.php).
Probably not fully working yet.

### Simple Binder

Trivial Jupyter notebook (print the Pi value). 
The test talks to [EGI Notebooks](https://replay.notebooks.egi.eu/) by default.
Change `#destination` in `ro-crate-metadata.json` eventually.

Zip the content of [test/simple-binder](test/simple-binder) and post the file to `/requests/zip_rocrate/`

### More realistict Binder

Testing notebook stolen from our other project, which takls to our service to find similar AlphaFold protein structures and displays their alignment.

Again, zip [test/alphafind-notebook](test/alphafind-notebook) and post the file to `/requests/zip_rocrate/`

### ScienceMesh
Testing for ScienceMesh is currently only local, in order to test it you can run the `test/sciencemesh/test_sciencemesh_class.py` server stub and then make a POST request to the Dispatcher with the provided ro-crate `test/sciencemesh/ro-crate-metadata.json` and you should see the server receiving the ro-crate as an embedded OCM (Open Cloud Mesh) share. A ScienceMesh node is being prepared to test this remotely in order to test with CERNBox.

