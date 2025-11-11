# Dispatcher API input examples

More description of these simple use cases in [top level README.md](../README.md).

How to use it:
1. make a flat zip file of the content of each of the directories here
2. POST it to `/requests/zip_rocrate` endpoint of the Dispatcher; the response contains `id` of the created requests
3. GET `/requests/<id returned by POST>` repeatedly until the request is ready; then the response contains a URL to the ready-to-use target service
