# Testing 

Virtual environment:
- Use virtual environment present in this project.
- Call `./venv/bin/pytest .` to run the tests.

Writing tests:
- Always test functionality and never test implementation. Never test private methods, only test public methods.
- Use mocks only when neccessary. When using mocks, don't test how many times a function was called or what the paramters are. Only test the output.
- Always use conftest.py and pytest.fixtures to configure tests instead of doing it inside the test. 

Fixing tests:
- Before fixing tests, run all tests and then analyze why they fail. Read the implementation first and then consider modifiyng tests.