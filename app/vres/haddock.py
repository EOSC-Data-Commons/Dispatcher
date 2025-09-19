import docker
import os
import shutil
from .base_vre import VRE

class VREHaddock(VRE):
    def __init__(self, crate, user_id):
        super().__init__(crate)
        self.user_id = user_id
        self.container = None
        self.workdir = f"/tmp/haddock_{user_id}"

    def prepare_data(self):
        os.makedirs(self.workdir, exist_ok=True)
        # Extract files from RO-Crate and copy to workdir
        for entity in self.crate.get_entities():
            if entity.type == "File":
                # Example: copy file to workdir
                src = entity.source_path
                dst = os.path.join(self.workdir, os.path.basename(src))
                shutil.copy(src, dst)

    def start_container(self):
        self.prepare_data()
        client = docker.from_env()
        self.container = client.containers.run(
            "haddock/haddock:latest",
            volumes={self.workdir: {'bind': '/data', 'mode': 'rw'}},
            ports={'8080/tcp': None},  # Expose Haddock UI/API port
            detach=True,
            tty=True,
            name=f"haddock_{self.user_id}"
        )
        return self.container

    def get_container_info(self):
        if self.container:
            self.container.reload()
            info = {
                "id": self.container.id,
                "status": self.container.status,
                "ports": self.container.attrs['NetworkSettings']['Ports'],
                "url": f"http://localhost:{self.container.attrs['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']}"
            }
            return info
        return None

    def stop_container(self):
        if self.container:
            self.container.stop()
            self.container.remove()
            shutil.rmtree(self.workdir, ignore_errors=True)

# Usage:
# vre = VREHaddock(crate, user_id)
# container = vre.start_container()
# info = vre.get_container_info()
# ... user interacts ...
# vre.stop_container()