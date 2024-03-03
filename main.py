# !/usr/bin/env python
# -*- coding: utf-8 -*

import logging,os,asyncio
from dotenv import load_dotenv
from telegram import Update,constansts
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,Filters

# Configure the logging;
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Load the environment variables;
load_dotenv()

# Check the ffmpeg download or the last version ,if not download it or update it;
gamdl.check_ffmpeg()
