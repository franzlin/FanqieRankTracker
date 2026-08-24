#!/bin/bash
# Fanqie rank daily pipeline: scrape -> build -> serve
set -e
cd /opt/fanqie-rank
export PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
export API_BASE_URL='https://api.lylwz.com/v1'
export API_KEY='Wa8/oUZvDCc6S+Cpv3ec6AK1L5zd9JdA'
export API_MODEL='gemini-3.7-flash-high'
export GITHUB_ACTIONS=1
LOG=/opt/fanqie-rank/logs/daily.log
mkdir -p logs
echo "===== [$(date '+%F %T')] pipeline start =====" >> $LOG
# 1. scrape (skip if today data already exists - script handles it)
./venv/bin/python scrape_fanqie_ranks.py >> $LOG 2>&1 || echo "SCRAPE FAILED" >> $LOG
# 2. build latest + AI summaries
./venv/bin/python scripts/build_latest.py >> $LOG 2>&1 || echo "BUILD FAILED" >> $LOG
echo "===== [$(date '+%F %T')] pipeline done =====" >> $LOG
