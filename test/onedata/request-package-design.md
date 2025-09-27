**RO-Crate design**
===============

This document sums up the concepts how to define relations to Onedata files/spaces in an RO-Crate (request package transmitted from the Request Packager to Dispatcher to run analysis).

One of the relevant aspects is how to carry the authentication/authorization.


### 1. Custom RO-Crate profile

In this approach, we specify a custom RO-Crate profile that will semantically describe a reference to data in Onedata.

##### Examples

1. Five Safes RO-Crate: 
  * https://dareuk.org.uk/how-we-work/ongoing-activities/trevolution/five-safes-ro-crate/
  * https://trefx.uk/5s-crate/0.4/
2. HERO-Crates: https://conference.eresearch.edu.au/hero-crates-hybrid-encrypted-research-object-crates-a-secure-method-for-storing-and-sharing-sensitive-metadata/


##### Auth (1)

Since we are defining the profile, we can decide on the approach:
1. Credentials are embedded in the RO-Crate in plain text:
    * ✅ OK if we know that the RO-Crates do not "leave" the system and are not published.
    * ❌ Conflicts with the idea of FAIR digital objects, reusability etc.
2. Credentials are encrypted in the RO-Crate:
    * ✅ The crates are not sensitive and can be published.
    * ❌ We need to maintain an infrastructure of keys between different components and partners.
      Or a system of permissions / access control.
3. See the [auth transmitted separately](#auth-4) proposition. 

##### Pros and cons

* ✅ Arguably elegant and most flexible.
* ❌ Considerable effort to define a profile and publish it.
* ❌ All components need to understand it and implement the logic.
* ❌ Lowers interoperability and takes as further from a generic solution.


### 2. onedata:// scheme 

We could use a custom `onedata://` scheme in the references, like this:

```json
  "@graph": [
    {
      "@id": "./",
      "@type": "Dataset",
      "name": "Example Crate Referencing Onedata",
      "hasPart": [
        {
          "@id": "onedata://datahub.egi.eu/my-space-name/data/sample.csv"
        }
      ]
    },
    {
      "@id": "onedata://datahub.egi.eu/my-space-name/data/sample.csv",
      "@type": "File",
      "name": "Sample CSV in Onedata",
      "encodingFormat": "text/csv",
      "contentUrl": "https://datahub.egi.eu/api/v3/shares/78adb6eabdc6d42adebbc/data/57896486742736421"
    },
    {"...": "..."}
  ]  
```

The `contentUrl` could be given as a fallback for clients that do not understand this notation.
* ❌ However, this makes sense only in case of public data; but then why bother with the new scheme at all?

##### Auth (2)

1. Credentials are embedded in the RO-Crate in plain text:
    * ✅ OK if we know that the RO-Crates do not "leave" the system and are not published.
    * ❌ Conflicts with the idea of FAIR digital objects, reusability etc.
    * ⚠️ Requires a custom implementation to retrieve them and use them:
        * ⚠️ One the dispatcher level: the dispatcher "unpacks" the auth and uses it to 
          prepare a package for a VRE that does not need authentication, such as creating
          a Onedata Remote in Galaxy. This may not be viable for all VREs.
        * ⚠️ On the level of every component/VRE - may be problematic to implement.
2. See the [auth transmitted separately](#auth-4) proposition. 

##### Pros and cons

* ✅ A little effort on the RO-Crate level construction and specification.
* ❌ Low interoperability - the crates will be incomprehensible without custom implementation client-side.
* ❌ All components need to understand it and implement the logic.


### 3. DCAT ?

An extension of proposition 2), with an attempt to better semantically describe Onedata 
as a data access service using the DCAT vocabulary:

```json
{
  "@context": [
    "https://w3id.org/ro/crate/1.1/context",
    {
      "dcat": "http://www.w3.org/ns/dcat#",
      "accessService": {
        "@id": "dcat:accessService",
        "@type": "@id"
      },
      "dcat:DataService": "dcat:DataService",
      "dcat:endpointURL": "dcat:endpointURL",
      "dcat:endpointDescription": "dcat:endpointDescription",
      "credentials": "https://schema.org/credentials"
    }
  ],
  "@graph": [
    {
      "@id": "./",
      "@type": "Dataset",
      "name": "Crate Referencing Onedata with Endpoint Info",
      "hasPart": [
        {
          "@id": "onedata://datahub.egi.eu/my-space-name/data/file1.csv"
        }
      ]
    },
    {
      "@id": "onedata://datahub.egi.eu/my-space-name/data/file1.csv",
      "@type": "File",
      "name": "Data in Onedata",
      "encodingFormat": "text/csv",
      "accessService": {
        "@id": "#my-onedata-access"
      }
    },
    {
      "@id": "#my-onedata-access",
      "@type": "dcat:DataService",
      "name": "onedata-compatible endpoint",
      "dcat:endpointURL": "https://datahub.egi.eu",
      "dcat:endpointDescription": "Compatible with Onedata API"
    }
  ]
}
```

##### Pros and cons

* ✅ Arguably more elegant and adhering to the ideas of RO-Crate extensibility.
* ❌ The same interoperability and implementation considerations as 2).


### 4. URL references & Auth transmitted separately 

Use standard URL references to data in Onedata. Develop a flexible reference system
on the level of Onedata to move the implementation weight away from clients.

```json
{
  "@graph": [
    {
      "@id": "./",
      "@type": "Dataset",
      "hasPart": [
        { "@id": "#textfile" },
      ]
    },
    {
      "@id": "#textfile",
      "@type": "File",
      "name": "text file in Onedata",
      "url": "https://datahub.egi.eu/ref/file:782634506821427836546723549247198",
      "encodingFormat": "text/txt"
    },
    {"...": "..."}
  ]
}
```

What's important in this approach that in the end, we always want to access **data**, be it 
files or directories. By shifting the weigh of resolving references to Onedata, we can keep
the RO-Crate clean:

```
https://datahub.egi.eu/ref/file:78263450682142783654672354924719887356487623411
https://datahub.egi.eu/ref/space:d0e4856e92f987e8f121997882abfe9f58a1a3c4
https://datahub.egi.eu/ref/archive:987e86e92f882abfe9f58a1a3c4f121997d0e485
https://datahub.egi.eu/ref/share:7298f882abe86e9fe9f58a1a3c4fe485121997d0
```

**DataHugger, FAIRiCAT**: we implement suitable interoperability extensions in Onedata so that 
it's possible to interact with the URLs using machines; they should be able to retrieve file 
metadata and directory listings using standardized methods. And, of course, the content.

**Embeddable Onedata file browser**: we will look into an embeddable version
of the Onedata app; it could be invoked in the EDC portal so that the user may choose from
his files/datasets/archives/shares using a GUI in an iframe. The EDC portal would get back
data references to be placed in the RO-Crate.


##### Auth (4)

Credentials are transmitted separately:
* ✅ We split the dataset/tool/VRE (analysis) description from the auth, which make sense as 
    they can be perceived orthogonal.
    * ✅ Different people can reuse the same RO-Crate and have different auths for running it.
* ✅ May give us better composition if we assume the flow through all the system is backed up by an
    OIDC token - which then becomes a separate parameter / header common for all the APIs.
    * ✅ We probably have to transmit the token to the VRE anyway, so that it runs the analysis on
      behalf of the user.
* ❌ We go away from the vision of "one request package to rule them all" that would carry EVERYTHING (this a problem though?).

##### Pros and cons

* See the [auth](#auth-4) considerations.
* ✅ Our RO-Crates are very generic and interoperable.
* ❌ We don't develop anything innovative in the context of RO-Crates - is this a problem?


## 5. Hybrid - URLs plus specific Onedata reference

We take proposition 4) to create a generic package, but also add an optional part with 
semantics specific for Onedata (profile? schema/vocabulary?). Recipients that understand
that can use **concrete Onedata interfaces** rather than the generic HTTP endpoint for data 
discovery/download:
* mount the data with Oneclient,
* access the data using pythonic interfaces,
* access the data using the REST API,
* create a Galaxy Remote Source for the user,
* ...

It could look like this:

```json
{
  "@context": [
    "https://w3id.org/ro/crate/1.1/context",
    {
      "onedata": "https://onedata.org/ro-crate-profile/1.0"
    }
  ],
  "@graph": [
    {
      "@id": "./",
      "@type": "Dataset",
      "hasPart": [
        { "@id": "#textfile" },
      ]
    },
    {
      "@id": "#textfile",
      "@type": "File",
      "name": "text file in Onedata",
      "encodingFormat": "text/txt",
      "url": "https://datahub.egi.eu/ref/file:782634506821427836546723549247198",
      "onedata:onezoneDomain": "datahub.egi.eu",
      "onedata:spaceId": "89437568932729873429834",
      "onedata:spaceName": "my-data",
      "onedata:fileId": "782634506821427836546723549247198",
      "onedata:publicAccess": false
    },
    {"...": "..."}
  ]
}
```

## 5a. Combining the above approach with Hybrid RO-Crate + BagIt

Based on the [RO-Crate documentation](https://www.researchobject.org/ro-crate/specification/1.1/appendix/implementation-notes.html#example-of-wrapping-a-bagit-bag-in-an-ro-crate).

```json
{
  "@context": [
    "https://w3id.org/ro/crate/1.1/context",
    {
      "onedata": "https://onedata.org/ro-crate-profile/1.0"
    }
  ],
  "@graph": [
    {
      "@id": "./bag1/data/",
      "@type": "Dataset",
      "hasPart": [
        { "@id": "bag1/data/packaged-file.csv" },
        { "@id": "bag1/data/remote-file.txt" }
      ]
    },
    {
      "@id": "bag1/data/packaged-file.csv",
      "@type": "File",
      "name": "CSV file included in the package",
      "encodingFormat": "text/csv"
    },
    {
      "@id": "bag1/data/remote-file.txt",
      "@type": "File",
      "name": "Remote text file in Onedata",
      "encodingFormat": "text/txt",
      "url": "https://datahub.egi.eu/ref/file:782634506821427836546723549247198",
      "onedata:onezoneDomain": "datahub.egi.eu",
      "onedata:spaceId": "89437568932729873429834",
      "onedata:spaceName": "my-data",
      "onedata:fileId": "782634506821427836546723549247198",
      "onedata:publicAccess": true
    },
    {"...": "..."}
  ]
}
```

The structure of the package could look like this:

```
<RO-Crate root>/
  |   ro-crate-metadata.json       # RO-Crate Metadata File MUST be present
  |   bag1/                        # "Wrapped" bag - could have any name
  |      bagit.txt                 # As per BagIt specification
  |      bag-info.txt              # As per BagIt specification
  |      manifest-<algorithm>.txt  # As per BagIt specification
  |      fetch.txt                 # Optional, per BagIt Specification
  |      data/
  |         packaged-file.csv
```

To ensure that the package can be fully rebuild using BagIt, the `fetch.txt` file should 
include the reference to `remote-file.txt`.