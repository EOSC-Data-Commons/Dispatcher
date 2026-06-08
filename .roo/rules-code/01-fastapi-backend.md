# Backend rules

Request handling:
- ROCrate Json and Zipfile with Rocrate are the only input formats.
- Inputs are parsed and a Request Package (RP) is built by Request Package builder
- Request Package is an abstraction to ROCrate and is the only way to access input data. No VRE or any other component is allowed to access or import ROCrate objects and library. If ROCrate is required by a VRE service, a raw ROCrate is available in the RP object. Never access parameters via the raw ROCrate.
- Request Package is accessible in ../vre-rocrate lib.
- Use Celery's `autoretry_for` for transient failures (e.g., [`GalaxyAPIError`](app/celery/tasks.py:29))
- Base Vre class has `_update_state`. Call it to report progress during long celery tasks.
- Calls to start VRE are asynchronous and the status is checked by calls to /status/{id}  
- Dispatcher supports creating underlying infrastructure for a specific services via Infrastructure Manager.

General:
- Hardcoded values should go in [`app/constants.py`](app/constants.py)
- Define contracts via `Protocol` classes (e.g., [`IMClientProtocol`](app/vres/base_vre.py:17))
- Never use native exceptions, use existing exceptions in app/exceptions.py or define new by inheriting the existing ones
- When refactoring, never merge functions into one. Keep separation of concerns

Code analysis
- Always run black formatter

