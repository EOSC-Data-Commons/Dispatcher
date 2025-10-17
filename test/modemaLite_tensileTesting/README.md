# 🧩 Notes on This RO-Crate

This repository provides an example **RO-Crate** for tensile testing analysis in materials science.
See [Tensile Testing on Wikipedia](https://en.wikipedia.org/wiki/Tensile_testing) for background.

### 🔍 Key Features

- Includes all **input files** directly within the RO-Crate.
- Contains a **`requirements.txt`** file specifying all libraries (with exact versions) to ensure reproducibility.
- Provides a **Python source file** inside the crate for running the analysis.

---

# 🛠️ Creating an RO-Crate

## 1. Setup Data

1. Clone the repository:
   ```bash
   git clone https://github.com/EOSC-Data-Commons/Dispatcher.git
   ```

2. Navigate to the test folder and create a new test directory. Create a file named ro-crate-metadata.json.

## 2. Validate the RO-Crate

Ensure the RO-Crate is complete and valid (including metadata and data files).

Install the Validator
``` bash
pip install roc-validator
```
Run Validation
``` bash
rocrate-validator validate modemaLite_tensileTesting/ -p ro-crate -f json
```

# 🚀 Testing the Dispatcher
1. Log In

   Go to the Dispatcher [login page](https://dev1.player.eosc-data-commons.eu/oauth2/login) and sign in.
   If you do not yet have an account, sign up [here](https://aai-demo.egi.eu/auth/realms/id/account/#/enroll?groupPath=/vo.eosc-data-commons.eu).

   💡 Tip:
   If you get an “unauthorized” error, close the browser completely and try again — a restart usually helps.

2. Test Dispatcher Functionality

   🧾 Get Token

   Open the GET /oauth2/token endpoint in the API docs.
   Click “Try it out” → “Execute”.

   You should receive a JSON object containing a token.

   Example CLI command:
   ``` bash
   curl -X 'GET' \
     'https://dev1.player.eosc-data-commons.eu/oauth2/token' \
     -H 'accept: application/json'
   ```
3. 📦 Zip and Submit the RO-Crate

   Open the POST /requests/zip_rocrate endpoint.

   - Click “Try it out”.
   - Zip your two files from test/simple-binder/.
   - Upload the ZIP file and click “Execute”.

   Example CLI command:
   ``` bash
   curl -X 'POST' \
     'https://dev1.player.eosc-data-commons.eu/requests/zip_rocrate/' \
     -H 'accept: application/json' \
     -H 'Content-Type: multipart/form-data' \
     -F 'zipfile=@test.zip;type=application/zip'
   ```
   You should receive a 200 OK response with a task_id.

4. 🧩 Check Task Status

   Use the returned task_id to check the status of your request:
   ``` bash
   curl -X 'GET' \
     'https://dev1.player.eosc-data-commons.eu/requests/3918dae4-cabb-438c-b86c-23d6c0f8ce25' \
     -H 'accept: application/json'
   ```
   Example response:
   ``` json
      {
        "task_id": "3918dae4-cabb-438c-b86c-23d6c0f8ce25",
        "status": "SUCCESS",
        "result": {
          "url": "https://replay.notebooks.egi.eu/v2/git/https%3A%2F%2Fdev1.player.eosc-data-commons.eu%2Fgit%2F457dc9fe-93c8-4af2-8cdd-356f33d650cd/HEAD"
        }
      }
   ```
   ✅ Success is guaranteed for this validated example.
   Visit the URL shown in the result to verify the output.

   ⚠️ Important: Close the page afterward — only one instance per user is allowed.

# 🧪 Running Your Own Dispatcher Job
1. Submit Your ZIP File

   Repeat the POST /requests/zip_rocrate step using your own ZIP file.
   A task_id will be returned if the submission succeeds.

2. Check Job Status

   Use GET /requests/{task_id} to check progress:

   If the job is running, you’ll see "status": "PENDING".

   On completion, "SUCCESS" or "FAILED" will appear.

   Success is not guaranteed, even if it says success — the Dispatcher simply forwards your job to the execution environment.

3. Open Binder

   Once your job succeeds, follow the provided Binder link to view your notebook or analysis results.

   - ⚠️ Common Binder Build Failures

     - You cannot login: starting a private-session in your browser helps

     - If your requirements.txt includes incompatible versions, the Binder build may fail.
     ```
     Example error:
     STEP 39/50: RUN ${KERNEL_PYTHON_PREFIX}/bin/pip install --no-cache-dir -r "requirements.txt"
     ERROR: Ignored the following versions that require a different Python version: 1.3.3 Requires-Python >=3.11
     ERROR: Could not find a version that satisfies the requirement contourpy==1.3.3
     ERROR: No matching distribution found for contourpy==1.3.3
     Check your Python version and ensure all dependencies in requirements.txt are compatible.
     ```
     - If you get "user aueoaeouaeo@egi.already has a running server"
       - Access https://replay.notebooks.egi.eu/hub/home to stop your running session before    starting a new one, aka retrying to use the url provided in the previous step.



✅ You’re done!
Your RO-Crate is now ready for validation, testing, and deployment with the Dispatcher system.