#!/usr/bin/env python3

import os
import shutil
from argparse import ArgumentParser

from oresat_configs import (
    CardsConfig,
    MissionConfig,
    load_od_configs,
    load_od_db,
    write_canopend_master,
    write_dbc,
    write_kaitai,
    write_xtce,
)

CONFIG_DIR_PATH = "configs"
CARDS_CONFIG_PATH = os.path.join(CONFIG_DIR_PATH, "cards.yaml")
MISSION_CONFIGS_PATHS = [
    os.path.join(CONFIG_DIR_PATH, "oresat0.yaml"),
    os.path.join(CONFIG_DIR_PATH, "oresat0_5.yaml"),
    os.path.join(CONFIG_DIR_PATH, "oresat1.yaml"),
]

GEN_DIR = "oresat_c3/gen"

parser = ArgumentParser()
parser.add_argument("gen", choices=["code", "dbc", "xtce", "kaitai", "clean"], default="code")
args = parser.parse_args()

cards_config = CardsConfig.from_yaml(CARDS_CONFIG_PATH)
mission_configs = [MissionConfig.from_yaml(p) for p in MISSION_CONFIGS_PATHS]

if args.gen == "code":
    write_canopend_master(cards_config, mission_configs, CONFIG_DIR_PATH, GEN_DIR)
elif args.gen == "dbc":
    od_configs = load_od_configs(cards_config, CONFIG_DIR_PATH)
    od_db = load_od_db(od_configs)
    write_dbc(od_db["c3"])
elif args.gen == "xtce":
    mission_config = mission_configs[0]  # TODO
    write_xtce(mission_config)
elif args.gen == "kaitai":
    mission_config = mission_configs[0]  # TODO
    write_kaitai(mission_config)
elif args.gen == "clean":
    shutil.rmtree(GEN_DIR, ignore_errors=True)
