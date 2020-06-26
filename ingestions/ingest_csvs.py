#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@author Christopher Wingard
@brief Reworks the original datateam_ingest code in the datateam_tools 
    repository to initiate ingest requests from the command line rather than
    from a propmt and response style of request.
"""
import argparse
import netrc
import pprint
import re
import requests
import sys

import datetime as dt
import pandas as pd

from pathlib import Path

# initialize requests session
HTTP_STATUS_OK = 200
HEADERS = {
    'Content-Type': 'application/json'
}
PRIORITY = 1

# initialize user credentials and the OOINet base URL
BASE_URL = 'https://ooinet.oceanobservatories.org'
credentials = netrc.netrc()
API_KEY, USERNAME, API_TOKEN = credentials.authenticators('ooinet.oceanobservatories.org')


def load_ingest_sheet(ingest_csv, ingest_type):
    """
    Loads the CSV ingest sheet and sets the ingest type used in subsequent steps
    
    :param ingest_csv: path and file name of the ingest CSV file to use
    :param ingest_type: ingestion type, telemetered (recurring) or recovered 
        (once only)
    :return df: pandas data frame with ingestion parameters
    """
    df = pd.read_csv(ingest_csv, usecols=[0, 1, 2, 3])
    df['username'] = USERNAME
    df['deployment'] = get_deployment_number(df.filename_mask.values)
    df['state'] = 'RUN'
    df['priority'] = PRIORITY
    if 'telemetered' in ingest_type:
        df['type'] = 'TELEMETERED'
    else:
        df['type'] = 'RECOVERED'

    return df


def get_deployment_number(filename_mask):
    """
    Pulls the deployment number out of the filename_mask field in the ingest 
    CSV file.
    
    :param filename_mask: filename mask, or regex, in the ingest CSV file that 
        includes the deployment number.
    :return deployment_number: the deployment number as an integer
    """
    deployment_number = []
    for fm in filename_mask:
        split_fm = fm.split('/')
        deployment_number.append(int(re.sub('.*?([0-9]*)$', r'\1', split_fm[5])))

    return deployment_number


def build_ingest_dict(ingest_info):
    """
    Converts the pandas dataframe information into the dictionary structure
    needed for the ingest request.
    
    :param ingest_info: information from the pandas dataframe to use in forming
        the ingest dictionary
    :return request_dict: ingest information structured as a dictionary
    """
    option_dict = {}
    keys = list(ingest_info.keys())

    adict = {k: ingest_info[k] for k in ('parserDriver', 'fileMask', 'dataSource', 'deployment',
                                         'refDes', 'refDesFinal') if k in ingest_info}
    request_dict = dict(username=ingest_info['username'],
                        state=ingest_info['state'],
                        ingestRequestFileMasks=[adict],
                        type=ingest_info['type'],
                        priority=ingest_info['priority'])

    for k in ['beginFileDate', 'endFileDate']:
        if k in keys:
            option_dict[k] = ingest_info[k]

    if option_dict:
        request_dict['options'] = dict(option_dict)

    return request_dict


def ingest_data(url, key, token, data_dict):
    """
    Post the ingest request to the OOI M2M api.
    
    :param url: Data ingest request URL for the M2M API
    :param key: Ingest users API key (from OOINet)
    :param token: Ingest users API token (from OOINet)
    :param data_dict: JSON formatted body of the POST request
    :return r: results of the request
    """
    r = requests.post('{}/api/m2m/12589/ingestrequest/'.format(url), json=data_dict, headers=HEADERS, auth=(key, token))
    if r.ok:
        return r
    else:
        pass


def main(argv=None):
    """
    Reads data from a CSV formatted file using the ingestion CSV structure to 
    create and POST an ingest request to the OOI M2M API.
    
    :param csvfile: CSV file with ingestion information
    :param ingest_type: specifies either a telemetered (recurring) or recovered
        (once only) ingest request type.
    :return: None, though results are saved as a CSV file in the directory the
        command is called from.
    """
    if argv is None:
        argv = sys.argv[1:]

    # initialize argument parser
    parser = argparse.ArgumentParser(description="""Sets the source file for the ingests and the type""")

    # assign input arguments.
    parser.add_argument("-c", "--csvfile", dest="csvfile", type=Path, required=True)
    parser.add_argument("-t", "--ingest_type", dest="ingest_type", type=str, choices=('recovered', 'telemetered'),
                        required=True)

    # parse the input arguments and create a parser object
    args = parser.parse_args(argv)

    # assign the annotations type and csv file
    ingest_csv = args.csvfile
    ingest_type = args.ingest_type

    # Initialize empty Pandas DataFrames
    pd.set_option('display.width', 1600)
    ingest_df = pd.DataFrame()

    # load the csv file for the ingests
    df = load_ingest_sheet(ingest_csv, ingest_type)
    df = df.sort_values(['deployment', 'reference_designator'])
    df = df.rename(columns={'filename_mask': 'fileMask', 'reference_designator': 'refDes',
                            'data_source': 'dataSource', 'parser': 'parserDriver'})
    df = df[pd.notnull(df['fileMask'])]

    unique_ref_des = list(pd.unique(df.refDes.ravel()))
    unique_ref_des.sort()

    # set cabled platforms to exclude from this process, those use a different method
    cabled = ['RS', 'CE02SHBP', 'CE04OSBP', 'CE04OSPD', 'CE04OSPS']
    cabled_reg_ex = re.compile('|'.join(cabled))
    cabled_ref_des = []
    for rd in unique_ref_des:
        if re.match(cabled_reg_ex, rd):
            cabled_ref_des.append(rd)

    # if the list of unique reference designators contains cabled instruments,
    # remove them from further consideration (they use a different system)
    if cabled_ref_des:
        for x in cabled_ref_des:
            unique_ref_des = [s for s in unique_ref_des if s != x]
            df.drop(df[df['refDes'] == x].index, inplace=True)

    # if all of the reference designators were for cabled systems, we are done
    if df.empty:
        print('Removed cabled array reference designators from the ingestion, no other systems left.')
        return None

    # add refDesFinal
    wcard_refdes = ['GA03FLMA-RIM01-02-CTDMOG000', 'GA03FLMB-RIM01-02-CTDMOG000',
                    'GI03FLMA-RIM01-02-CTDMOG000', 'GI03FLMB-RIM01-02-CTDMOG000',
                    'GP03FLMA-RIM01-02-CTDMOG000', 'GP03FLMB-RIM01-02-CTDMOG000',
                    'GS03FLMA-RIM01-02-CTDMOG000', 'GS03FLMB-RIM01-02-CTDMOG000']

    df['refDesFinal'] = ''
    pp = pprint.PrettyPrinter(indent=2)
    for row in df.iterrows():
        # skip commented out entries
        if '#' in row[1]['parserDriver']:
            continue
        elif row[1]['parserDriver']:
            rd = row[1].refDes
            if rd in wcard_refdes:
                # the CTDMO decoder will be invoked
                row[1].refDesFinal = 'false'
            else:
                # the CTDMO decoder will not be invoked
                row[1].refDesFinal = 'true'

            ingest_dict = build_ingest_dict(row[1].to_dict())
            pp.pprint(ingest_dict)
            review = input('Review ingest request. Is this correct? <y>/n: ') or 'y'
            if 'y' in review:
                r = ingest_data(BASE_URL, API_KEY, API_TOKEN, ingest_dict)
                print(r)
                ingest_json = r.json()
                tdf = pd.DataFrame([ingest_json], columns=list(ingest_json.keys()))
                tdf['ReferenceDesignator'] = row[1]['refDes']
                tdf['state'] = row[1]['state']
                tdf['type'] = row[1]['type']
                tdf['deployment'] = row[1]['deployment']
                tdf['username'] = row[1]['username']
                tdf['priority'] = row[1]['priority']
                tdf['refDesFinal'] = row[1]['refDesFinal']
                tdf['fileMask'] = row[1]['fileMask']
                ingest_df = ingest_df.append(tdf)
            else:
                print('Skipping this ingest request')
                continue
        else:
            continue

    # save the results
    print(ingest_df)
    utc_time = dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    ingest_df.to_csv('{}_ingested.csv'.format(utc_time), index=False)

if __name__ == '__main__':
    main()