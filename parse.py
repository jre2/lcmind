#!/usr/bin/env python
#-*- coding: utf-8 -*-

import glob
import numpy as np
import os
from   pprint import pprint
import re

log_times = {} # Log -> [RunTimeFloat]
log_score = {} # Log -> (NumWins, NumLosses)

for path in glob.glob('r:/tmp/logs/limbus_company/console*.txt'):
    filename = os.path.basename( path )
    m = re.search( "console_2024-11-(.*).txt", filename )
    log_name = m.group(1)
    with open( path, 'r' ) as file:
        for line in file:
            m = re.search( r"complete.*'run time': '([\d.]+)'", line )
            if m:
                run_time = float( m.group(1) )
                if log_name not in log_times:
                    log_times[ log_name ] = []
                log_times[ log_name ].append( run_time )
            m = re.search( r"complete.*'wins': ([\d.]+).*losses': ([\d.]+)", line )
            if m:
                wins = int( m.group(1) )
                losses = int( m.group(2) )
                #if sum(log_score.get( log_name, (0,0) )) < sum( (wins,losses) ): # not needed since log ordered by time
                log_score[ log_name ] = ( wins, losses )


for log_name,log_times in sorted( log_times.items() ):
    wins, losses = log_score[ log_name ]
    rate = wins / (wins+losses)
    log_times = sorted(log_times)
    # iter 1
    mean = np.mean( log_times )
    stdev = np.std( log_times )
    times = [ rt for rt in log_times if abs(rt - mean) / stdev <= 3 or stdev < 0.05 ]
    # iter 2
    mean = np.mean( times )
    stdev = np.std( times )
    times = [ rt for rt in log_times if abs(rt - mean) / stdev <= 3 or stdev < 0.05 ]
    # final
    mean = np.mean( times )
    stdev = np.std( times )
    #print( log_name, min(times), max(times), mean, stdev )
    #print( 'raw ', log_times )
    #print( 'cull', times )
    print( f"{log_name} {rate*100:5.1f}% {mean:.1f} min -- {wins:2} W {losses:2} L -- {times}" )
