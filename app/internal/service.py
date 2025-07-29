from app.internal.im import IM
from app.internal.vre import VRE

def service_factory(vre: VRE):
    svc = vre.root.get("runsOn")
   
    if svc is None:
        return svc
    if svc.get("type") == "Service":
        return svc
    elif svc.get("type") == "SoftwareApplication":
        # Send this destination to the IM to deploy the service
        # and get the URL of the deployed service
        # For now only IM, should be extended to other service providers
        im = IM(self.access_token)
        service_url = im.run_service(svc)
        if outputs is None:
            raise HTTPException(
                status_code=400, detail="Failed to deploy service"
            )
        vre.root["runsOn"] =  {
            "@id": "#destination",
            "@type" : "Service",
            "url": service_url
        }
        return vre

    else:
        raise HTTPException(
            status_code=400, detail="Invalid service type in runsOn"
        )
