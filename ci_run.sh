#!/usr/bin/env bash
set -e

mkdir -p out

if [ -x "./handsfree_runner_plus.sh" ]; then
  ./handsfree_runner_plus.sh
elif [ -x "./handsfree_runner.sh" ]; then
  ./handsfree_runner.sh
else
  echo "❌ No handsfree runner found."
  exit 1
fi

git config user.name "props-bot"
git config user.email "props-bot@users.noreply.github.com"

git add -A out/

if git diff --cached --quiet; then
  echo "No new changes to commit."
else
  git commit -m "Daily NFL props auto-update"
  git push
fi