#!/usr/bin/python

import sys
import re

file_name = sys.argv[0]
#print file_name

def split_line(line,delim):
    return line.rsplit(delim)

def get_data(filename,attr):
    print "Printing " + attr
    file = open(filename,'r')
    flag = 0
    result = []
    for line in file:
        m=re.search(attr,line)
        if m:
            if line[-1]=='\n': line=line[:-1] 
            result = split_line(line,":")
            print result[len(result)-1]
            break

    m = re.search("}",line)
    if m:
        flag = 1;
    else:
        for line in file:
            m=re.search("}",line)
            if m:
                break
            else:
                if line[-1]=='\n': line=line[:-1] #printing the inetrmeditae lines
                result = split_line(line,":")
                print result[len(result)-1]

    if flag:
        pass
    else:
        if line[-1]=='\n': line=line[:-1] #printing the last line
        result = split_line(line,":")
        print result[len(result)-1]

get_data(file_name,"'passwords':")
get_data(file_name,"'usernames':")



  
