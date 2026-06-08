# Deploy project

Steps:
- Use testing environment to test the deployment. 
- `cd ansible/`
- Call `ansible-playbook dispatcher-dev.yml -T 50 --limit=dev3.player.eosc-data-commons.eu`. 
- Once this deployment finishes, ssh to the machine to verify all containers from `docker-compose.yml.j2` is running.
- Use `ssh ubuntu@dev3.player.eosc-data-commons.eu` to connect to the instance.
- Run `sudo docker` for any docker command