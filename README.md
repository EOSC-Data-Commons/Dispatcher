**Dispatcher**
===============

A **WORK-IN-PROGRESS** prototype of EDC Dispatcher, see also [Dispatcher page](https://confluence.egi.eu/display/EOSCDATACOMMONS/Dispatcher+draft) in project Confluence.

**Note:** This is a proof-of-concept implementation and should not be used in production without further testing and refinement.

**Overview**
------------

Dispatcher is a component which consumes a ROCrate object (either ZIP file or just its `ro-crate-metadata.json`) containing references to workflow and its input files, 
and instantiates an environment for the user, where the data are available and the workflow can be started.

The ROCrate profile Dispatcher recognizes is not fully defined yet, follow examples in [test/](test/).

The endpoint accepts requests at the paths:
- `/requests/zip_rocrate`: POST, ROCrate as a zip file in the body
- `/requests/metadata_rocrate`: POST, only the `ro-crate-metatada.json` in the body

On successful completition, a URL pointing to the prepared environment is returned.

**Current restrictions:**
- Only Galaxy works now
- Jupiter/Binder is not fully implemented yet
- Requests are processed synchronously (not queued if the completition takes longer, no real requests status/lifecycle implemented)
- No user authentication yet

**Getting Started**
-------------------

To run Dispatcher, follow these steps:

1. Clone this repository: `git clone https://github.com/EOSC-Data-Commons/Dispatcher.git`
2. Build the Docker image: `docker build -t dispatcher .`
3. Run the Docker container: `docker run -d -p 8000:8000 dispatcher`

This will start the API server on `localhost:8000`.

Alternatively, a Python virtual environment can be created, dependencies installed from [requirements.txt](requirements.txt), and the server started with:
```
uvicorn app.main:app --port 8000
```


**Example API Calls**
--------------------

### Galaxy

Going to https://test.galaxyproject.org/,
Dispatcher creates a landing page with simple workflow, that accepts a `txt` file and creates its reversed copy.

Just post the metadata file to the endpoint:
```
curl http://localhost:8000/requests/metadata_rocrate/ -X POST -H "Content-Type: application/json" --data @test/galaxy/ro-crate-metadata.json
```

### Simple Binder

Trivial Jupyter notebook (print the Pi value). 
The test talks to our Binder service; it would be better to use https://mybinder.org/ but it blocks communication to non-standard ports,
which we use for testing typically.
Change `#destination` in `ro-crate-metadata.json` eventually.

```
cd test/simple-binder
../post_zip.py http://localhost:8000/requests/zip_rocrate/ notebook.ipynb
```

### More realistict Binder

Testing notebook stolen from our other project, which takls to our service to find similar AlphaFold protein structures and displays their alignment.

```
cd test/alphafind-notebook
../post_zip.py http://localhost:8000/requests/zip_rocrate/ multi-domain-search.ipynb requirements.txt
```
