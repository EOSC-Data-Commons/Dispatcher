#!/usr/bin/env python3

import uvicorn
import argparse 
import os
import yaml
import logging

import app.internal.config as config

    
def main():
    config.config = None

    parser = argparse.ArgumentParser(description="EDC Dispatcher")
    parser.add_argument('--config', type=str, help='YAML configuration file')
    parser.add_argument('--host', type=str, default='localhost', help='address to listen')
    parser.add_argument('--port', type=int, help='port to listen')
    parser.add_argument('--debug', action='store_true', help='debug')
    
    args, _ = parser.parse_known_args()
    config_path = args.config or os.getenv('CONFIG_PATH')
    
    if not config_path:
        raise ValueError("Configuration file path must be specified via command-line or environment variable.")
    
    with open(config_path, 'r') as file:
        config.config = yaml.safe_load(file)

    print(str(config.config))
    
    port = args.port or int(config.config['api']['port'])
    
    log_level = logging.INFO
    if args.debug: 
        log_level = logging.DEBUG
    uvicorn.run("app.main:app", host=args.host, port=port, log_level=log_level)

if __name__ == "__main__":
    main()
