# Dispatcher API input examples

Example RO-Crate metadata files have been moved to the [vre-rocrate](https://github.com/EGI-Federation/vre-rocrate) library.
See `vre-rocrate/tests/fixtures/` for example RO-Crate JSON files for each VRE type (galaxy, jupyter, binder, oscar, sciencemesh, vip, scipion, etc.).

How to use it:
1. make a flat zip file of the content of one of the fixture directories in vre-rocrate
2. POST it to `/requests/zip_rocrate` endpoint of the Dispatcher; the response contains `id` of the created requests
3. GET `/requests/<id returned by POST>` repeatedly until the request is ready; then the response contains a URL to the ready-to-use target service
