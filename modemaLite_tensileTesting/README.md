# TODO
- test dispatcher: first given example, then mine.
    https://dispatcher.edc.cloud.e-infra.cz/docs#/oauth2/get_token-oauth2_token-get
- continue documenting

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
