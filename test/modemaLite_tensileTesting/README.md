# Notes on this ro-crate
RO-crate example of tensile-testing analysis in materials science [wikipedia](https://en.wikipedia.org/wiki/Tensile_testing). Some features of this example
- the input-files inside the ro-crate
- uses a requirements file to define all libraries, incl. the exact version (to allow to verify reproducibility)
- uses an python source file inside the ro-crate

# When creating an ro-crate

## Setup data
1. go to [github](https://github.com/EOSC-Data-Commons/Dispatcher) and clone repository
2. go to test folder and create a new test
1. go into it and create two folders (input and source),
   - put the research data into input.
   - put a starting source file YYY and a requirements.txt file into source. Make sure the YYY file runs successfully.
2. create ro-crate-metadata.json inside the test folder

## Validate
Validate that the ro-crate is fulfilling the requirements (incl. metadata.json and data-files)
1. install
   ``` bash
   pip install roc-validator
   ```
2. execute
   ``` bash
   rocrate-validator validate modemaLite_tensileTesting/ -p ro-crate -f json
   ```

## Dispatcher: test it
Go to [dispatcher](https://dev1.player.eosc-data-commons.eu/oauth2/login) and see if you can log-in. You can [sign up](https://aai-demo.egi.eu/auth/realms/id/account/#/enroll?groupPath=/vo.eosc-data-commons.eu). Please note that when you get an unauthorized error: it is good to close the browser to start again and see if a restart helps.
1. **Test if dispatcher works**: Go to "GET /oauth2/token Get Token" and click **"Try it out"** and **"Execute"**. You should get a json with a token.
   ``` bash
   curl -X 'GET' 'https://dev1.player.eosc-data-commons.eu/oauth2/token' -H 'accept: application/json'
   ```
2. **Test if services are executed**: Go to "POST /requests/zip_rocrate/ Zip Rocrate" and click **"Try it out"**. Go to the data folder on your computer, zip the two files in test/simple-binder and upload that zip file. Click **"Execute"**

   ``` bash
   curl -X 'POST' 'https://dev1.player.eosc-data-commons.eu/requests/zip_rocrate/' -H 'accept: application/json' -H 'Content-Type: multipart/form-data' -F 'zipfile=@test.zip;type=application/zip'
   ```
   You should get a 200-response body with a task_id.

   You have to use that task_id at the GET /requests/{task_id} Status" endpoint. **"Try it out"**, paste in the task_id and click **"Execute"**
   ``` bash
   curl -X 'GET'  'https://dev1.player.eosc-data-commons.eu/requests/3918dae4-cabb-438c-b86c-23d6c0f8ce25' -H 'accept: application/json'
   ```
   You should get a 200-response body with a json
   ``` json
   {
      "task_id": "3918dae4-cabb-438c-b86c-23d6c0f8ce25",
      "status": "SUCCESS",
      "result": {
         "url": "https://replay.notebooks.egi.eu/v2/git/https%3A%2F%2Fdev1.player.eosc-data-commons.eu%2Fgit%2F457dc9fe-93c8-4af2-8cdd-356f33d650cd/HEAD"
         }
      }
   ```
   Success is guaranteed, since this is a validated example. Go to that page and check. **CLOSE THE PAGE AFTERWARDS** (only one instance is allowed for each user)

## Dispatcher
1. Send the zip file of your job off: Go to "POST /requests/zip_rocrate/ Zip Rocrate" and click **"Try it out"**. Go to the data folder on your computer, zip the two files in test/simple-binder and upload that zip file. Click **"Execute"**
   -  You should get a 200-response body with a task_id.
2. Use task_id with the server at the GET /requests/{task_id} Status" endpoint. **"Try it out"**, paste in the task_id and click **"Execute"**
   - You should get a 200-response body with a json
   - Success in not guaranteed, just dispatcher send it off. Go to that page and check.
3. Binder website
   - Example failures
     - requirements.txt file does not work
         ```
         STEP 39/50: RUN ${KERNEL_PYTHON_PREFIX}/bin/pip install --no-cache-dir -r "requirements.txt"
         ERROR: Ignored the following versions that require a different python version: 1.3.3 Requires-Python >=3.11
         ERROR: Could not find a version that satisfies the requirement contourpy==1.3.3 (from versions: 0.0.1, 0.0.2, 0.0.3, 0.0.4, 0.0.5, 1.0.0, 1.0.1, 1.0.2, 1.0.3, 1.0.4, 1.0.5, 1.0.6, 1.0.7, 1.1.0, 1.1.1rc1, 1.1.1, 1.2.0, 1.2.1rc1, 1.2.1, 1.3.0, 1.3.1, 1.3.2)
         ERROR: No matching distribution found for contourpy==1.3.3
         ```
