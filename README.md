**Dispatcher**
===============

A **WORK-IN-PROGRESS** prototype of Dispatcher that serves as an API endpoint to launch the Galaxy landing page and return its URL, supporting ROCrate as its input format.

**Overview**
------------

This project uses Docker to containerize a Django application that exposes a single POST endpoint, `/requests/`. When called, this endpoint launches the Galaxy landing page and returns the URL of the launched page.

**Note:** This is a proof-of-concept implementation and should not be used in production without further testing and refinement.

**Getting Started**
-------------------

To run Dispatcher, follow these steps:

1. Clone this repository: `git clone https://github.com/EOSC-Data-Commons/Dispatcher.git`
2. Build the Docker image: `docker build -t dispatcher .`
3. Run the Docker container: `docker run -d -p 8000:8000 dispatcher`

This will start the API server on `localhost:8000`. You can then send a POST request to `http://localhost:8000/requests/` to launch the Galaxy landing page and receive its URL in response.

**API Endpoint**
----------------

* **POST /requests/**: Launches the Galaxy landing page and returns the URL of the launched page. The request body should contain a JSON payload with the necessary metadata, such as:
```json
{
  "@context": "https://w3id.org/ro/crate/1.1/context",
  "@graph": [
    // ... (see example below)
  ]
}
```
**Example API Call**
--------------------

You can use following `curl` request to test the API endpoint. It creates a landing page with simple workflow, that accepts a `txt` file and creates its reversed copy:
```bash
curl localhost:8000/requests/ -X POST -H "Content-Type: application/json" --data '{
    "@context": "https://w3id.org/ro/crate/1.1/context",
    "@graph": [
        {
            "@id": "./",
            "@type": "Dataset",
            "datePublished": "2025-05-06T14:35:47+00:00",
            "hasPart": [
                {
                    "@id": "https://dockstore.org/api/ga4gh/trs/v2/tools/%23workflow%2Fgithub.com%2Flaitanawe%2Fismb2024%2Fgalaxy_example/versions/main/PLAIN_GALAXY/descriptor//Galaxy-Workflow-reverse_file_galaxy_workflow.ga"
                },
                {
                    "@id": "https://example-files.online-convert.com/document/txt/example.txt"
                }
            ]
        },
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "about": {
                "@id": "./"
            },
            "conformsTo": {
                "@id": "https://w3id.org/ro/crate/1.1"
            }
        },
        {
            "@id": "https://dockstore.org/api/ga4gh/trs/v2/tools/%23workflow%2Fgithub.com%2Flaitanawe%2Fismb2024%2Fgalaxy_example/versions/main/PLAIN_GALAXY/descriptor//Galaxy-Workflow-reverse_file_galaxy_workflow.ga",
            "@type": [
                "File",
                "SoftwareSourceCode",
                "ComputationalWorkflow"
            ],
            "name": "Example galaxy workflow",
            "programmingLanguage": {
                "@id": "https://w3id.org/workflowhub/workflow-ro-crate#galaxy"
            },
            "url": "https://dockstore.org/api/ga4gh/trs/v2/tools/%23workflow%2Fgithub.com%2Flaitanawe%2Fismb2024%2Fgalaxy_example/versions/main/GALAXY/files?format=zip"
        },
        {
            "@id": "https://w3id.org/workflowhub/workflow-ro-crate#galaxy",
            "@type": "ComputerLanguage",
            "identifier": {
                "@id": "https://galaxyproject.org/"
            },
            "name": "Galaxy",
            "url": {
                "@id": "https://galaxyproject.org/"
            }
        },
        {
            "@id": "https://example-files.online-convert.com/document/txt/example.txt",
            "@type": "File",
            "name": "simpletext_input",
            "encodingFormat": "text/txt"
        }
    ]
}'
```
