#!/bin/sh
tail -F "$(ls -t r:/tmp/logs/limbus_company/console*.txt |head -1)"
