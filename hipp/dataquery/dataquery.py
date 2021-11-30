import cv2
import concurrent
import glob
import json
import os
import pathlib
import numpy as np
import pandas as pd
import psutil
import requests
import sys
import time
import urllib

import hipp


"""
Library query and download historical image data from public archives.
"""

### GENERIC FUNCTIONS

def _download_image(output_directory, 
                   payload,
                   default_img_ext = '.tif'):
    url, file_name = payload
    path_name, base_name, ext = hipp.io.split_file(os.path.abspath(file_name))
    if ext == '':
        output_file = os.path.join(output_directory, base_name + default_img_ext)
    else:
        output_file = os.path.join(output_directory, base_name + ext)
    urllib.request.urlretrieve(url,output_file)
    return output_file

def _thread_downloads(output_directory, urls, file_names, max_workers=5):
    
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    future_to_url = {pool.submit(_download_image,
                                 output_directory,
                                 x): x for x in zip(urls, file_names)}
    results=[]
    for future in concurrent.futures.as_completed(future_to_url):
        r = future.result()
        results.append(r)
        print('Download complete for:',r)

def EE_download_images_to_disk(
    apiKey,
    entityIds,
    label                                = 'test_download',
    output_directory                     = 'input_data',
    images_directory_suffix              = 'raw_images',
    calibration_reports_directory_suffix = 'calibration_reports'
):
    
    urls, file_names = _EE_stageForDownload(apiKey, entityIds, label = label)
    #one possible download mode - has file names...                                                          
    if file_names:                                                        
        pathlib.Path(output_directory).mkdir(parents=True, exist_ok=True)
        
        _thread_downloads(output_directory, 
                                        urls, 
                                        file_names)
                                        
        hipp.io.gunzip_dir(output_directory)
        # hipp.utils.optimize_geotifs(output_directory)
        
        images_directory              = os.path.join(output_directory, images_directory_suffix)
        calibration_reports_directory = os.path.join(output_directory, calibration_reports_directory_suffix)
        
        hipp.io.move_files(output_directory, images_directory, '.tif')
        hipp.io.move_files(output_directory, calibration_reports_directory, '.pdf')
        
        print('Images in:', images_directory)
        print('Calibration reports in:', calibration_reports_directory)
        
        return images_directory, calibration_reports_directory
    
    else:
        return None, None
    
def _EE_convert_api_responses_to_dataframe(scenes):
    # Reference: https://lta.cr.usgs.gov/DD/aerial_single_frame.html
    # dictionary relating the field names used by the EE API
    # to the HIPP/HSFM preferred column names
    api_to_hsfm_field_name_dict = {
        'Entity  ID':                       'entityId',
        'Agency':                           'agency',
        'Project':                          'project',
        'Roll':                             'roll',
        'Frame':                            'frame',
        'Recording Technique':              'recordingTechnique',
        'Acquisition Date':                 'acquisitionDate',
        'High Resolution Download Avail':   'hi_res_available',
        'Image Type':                       'imageType',
        'Quality':                          'quality',
        'Flying Height in Feet':            'altitudesFeet',
        'Photo ID':                         'imageId',
        'Focal Length':                     'focalLength',
        'Center Latitude dec':              'centerLat',
        'Center Longitude dec':             'centerLon',
        'NW Corner Lat dec':                'NWlat',
        'NW Corner Long dec':               'NWlon',
        'NE Corner Lat dec':                'NElat',
        'NE Corner Long dec':               'NElon',
        'SE Corner Lat dec':                'SElat',
        'SE Corner Long dec':               'SElon',
        'SW Corner Lat dec':                'SWlat',
        'SW Corner Long dec':               'SWlon',
    }

    #Iterate over api results creating a dataframe for each and appending into one dataframe
    scenes_df = pd.DataFrame()
    for scene in scenes:
        #This pandas work converts the tidy format of the API response to a column-organized dataframe
        one_scene_df = pd.DataFrame(scene['metadata'])
        one_scene_df = one_scene_df[one_scene_df.fieldName.isin(api_to_hsfm_field_name_dict.keys())]
        one_scene_df = one_scene_df[['fieldName', 'value']].set_index(
            'fieldName'
            ).transpose().rename_axis(
                None, 
                axis = 1
            ).reset_index(drop=True)
        scenes_df = scenes_df.append(one_scene_df)

    #Rename column names to the HIPP/HSFM preferred column names
    scenes_df = scenes_df.rename(api_to_hsfm_field_name_dict, axis=1)
    #Clean up the combined dataframe

    #get rid of the mm part of the "focalLength" column and make it a float
    scenes_df['focalLength'] = scenes_df['focalLength'].apply(lambda s: s.split(' ')[0])

    #Make numeric columns type float
    convert_dict = {
        'altitudesFeet': float,
        'focalLength': float,
        'centerLat': float,
        'centerLon': float,
        'NWlat': float,
        'NWlon': float,
        'NElat': float,
        'NElon': float,
        'SElat': float,
        'SElon': float,
        'SWlat': float,
        'SWlon': float
    }
    
    scenes_df = scenes_df.astype(convert_dict)

    scenes_df = scenes_df.reset_index(drop=True)

    return scenes_df
    
def EE_login(username,
             password,
             m2mhost = 'https://m2m.cr.usgs.gov/api/api/json/stable/'):

    data = {'username' : username, 
            'password' : password}
    
    url = m2mhost + 'login'
    api_key = _EE_sendRequest(url, data)
    
    return api_key

def EE_pre_select_images(apiKey,
                   xmin,ymin,xmax,ymax,
                   startDate,endDate,
                   metadataType = 'full', #'summary', None
                   maxResults   = 2,
                   datasetName  = 'aerial_combin',
                   serviceUrl   = 'https://m2m.cr.usgs.gov/api/api/json/stable/'):
    """
    Example inputs:
    xmin       = -114.5
    ymin       = 48.2
    xmax       = -113.0
    ymax       = 49.2
    start_date = '1966-01-01'
    end_date   = '1966-12-10'     
    """
    print('Max records requested:',maxResults)
    print('\nBounds:\nxmin', xmin,'\nymin', ymin,'\nxmax',xmax,'\nymax',ymax)
    print('\nTime range:', startDate,'to', endDate)
    
    spatialFilter =  {'filterType' : "mbr",
                      'lowerLeft'  : {'latitude' : ymin, 'longitude' : xmax},
                      'upperRight' : {'latitude' : ymax, 'longitude' : xmin}}
    acquisitionFilter = {'start' : startDate, 'end' : endDate}
    datasetSearchParameters = {'datasetName' : datasetName,
                               'maxResults' : maxResults,
                               'sceneFilter' : {'spatialFilter'     : spatialFilter,
                                                'acquisitionFilter' : acquisitionFilter},
                               'metadataType': metadataType}
    scenes = _EE_sendRequest(serviceUrl + "scene-search", datasetSearchParameters, apiKey)
    print('\nRecords returned:', scenes['recordsReturned'])
    if scenes['recordsReturned'] == maxResults:
        print("\nmaxResults set to:", maxResults, 
              '\nIncrease this parameter to obtain additional records. API max 50,000.')
    
    results_df = _EE_convert_api_responses_to_dataframe(scenes['results'])
    return results_df
    
def _EE_sendRequest(url, data, apiKey = None):  
    json_data = json.dumps(data)
    
    if apiKey == None:
        response = requests.post(url, json_data)
    else:
        headers = {'X-Auth-Token': apiKey}              
        response = requests.post(url, json_data, headers = headers)    
    
    try:
        httpStatusCode = response.status_code
        if response == None:
            print("No output from service")
            sys.exit()
        output = json.loads(response.text)
        if output['errorCode'] != None:
            print(output['errorCode'], "- ", output['errorMessage'])
            sys.exit()
        if  httpStatusCode == 404:
            print("404 Not Found")
            sys.exit()
        elif httpStatusCode == 401: 
            print("401 Unauthorized")
            sys.exit()
        elif httpStatusCode == 400:
            print("Error Code", httpStatusCode)
            sys.exit()
    except Exception as e:
        response.close()
        print(e)
        sys.exit()
    response.close()
    
    return output['data']

def _EE_stageForDownload(apiKey,
                        entityIds,
                        label        = 'test_download',
                        datasetName  = 'aerial_combin',
                        serviceUrl   = 'https://m2m.cr.usgs.gov/api/api/json/stable/'):
    
    
    """Stage downloads using the EarthExplorer api and a given list of entityIds

    Products/requests are filtered such that only requests with "collectionName" equal to "Aerial Photo Single Frames"
    and with "productName" that is equal to either "Camera Calibration File" or "High Resolution Product"

    API request handling adapted from usgs example https://m2m.cr.usgs.gov/api/docs/example/download_data-py

    Returns:
        urls, filenames: tuple of urls and names for the files
    """
    ee_requests = []
    # download datasets
    
    payload = {'datasetName' : datasetName, 'entityIds' : entityIds}
                        
    downloadOptions = _EE_sendRequest(serviceUrl + "download-options", payload, apiKey)

    # Aggregate a list of available products
    downloads = []
    for product in downloadOptions:
            # Make sure the product is available for this scene
            if product['available'] == True:
                    downloads.append({'entityId' : product['entityId'],
                                    'productId' : product['id']})
                    
    # Did we find products?
    if downloads:
        requestedDownloadsCount = len(downloads)
        # set a label for the download request
        label = "download-sample"
        payload = {'downloads' : downloads,
                                        'label' : label}
        # Call the download to get the direct download urls
        requestResults = _EE_sendRequest(serviceUrl + "download-request", payload, apiKey)          
                        
        # PreparingDownloads has a valid link that can be used but data may not be immediately available
        # Call the download-retrieve method to get download that is available for immediate download
        if requestResults['preparingDownloads'] != None and len(requestResults['preparingDownloads']) > 0:
            payload = {'label' : label}
            moreDownloadUrls = _EE_sendRequest(serviceUrl + "download-retrieve", payload, apiKey)
            
            downloadIds = []  
            
            for download in moreDownloadUrls['available']:
                downloadIds.append(download['downloadId'])
                print("DOWNLOAD: " + download['url'])
                print("NAME: " + download['entityId'])
                ee_requests.append(download)
                
            for download in moreDownloadUrls['requested']:   
                downloadIds.append(download['downloadId'])
                print("DOWNLOAD: " + download['url'])
                print("NAME: " + download['entityId'])
                ee_requests.append(download)
                
            # Didn't get all of the requested downloads, call the download-retrieve method again probably after 30 seconds
            while len(downloadIds) < requestedDownloadsCount: 
                preparingDownloads = requestedDownloadsCount - len(downloadIds)
                print("\n", preparingDownloads, "downloads are not available. Waiting for 30 seconds.\n")
                time.sleep(30)
                print("Trying to retrieve data\n")
                moreDownloadUrls = _EE_sendRequest(serviceUrl + "download-retrieve", payload, apiKey)
                for download in moreDownloadUrls['available']:                            
                    if download['downloadId'] not in downloadIds:
                        downloadIds.append(download['downloadId'])
                        print("DOWNLOAD: " + download['url'])
                        print("NAME: " + download['entityId'])
                        ee_requests.append(download)
                    
        else:
            # Get all available downloads
            for download in requestResults['availableDownloads']:
                # TODO :: Implement a downloading routine
                print("DOWNLOAD: " + download['url'])
                print("NAME: " + download['entityId'])
                ee_requests.append(download)
        print("\nAll downloads are available to download.\n")

        # Download images
    filtered_reqs = [
        rq for rq in ee_requests
        if rq['collectionName'] == 'Aerial Photo Single Frames' and rq['productName'] in ['Camera Calibration File', 'High Resolution Product']
    ]

    urls = []
    filenames = []
    for req in filtered_reqs:
        if req['productName'] =='Camera Calibration File':
            name = req['entityId'] + '.pdf'
        else:
            name = req['entityId'] + '.tif.gz'
        urls.append(req['url'])
        filenames.append(name)
    
    return urls, filenames

## ARCTICDATA.IO

def NAGAP_download_images_to_disk(image_metadata, 
                                  output_directory='input_data/raw_images',
                                  file_name_column='fileName',
                                  image_type_colum='pid_tiff',
                                  base_url = 'https://arcticdata.io/metacat/d1/mn/v2/object/',
                                  verbose=True):
                            
    print("Downloading images...")
    p = pathlib.Path(output_directory)
    p.mkdir(parents=True, exist_ok=True)
    
    if not isinstance(image_metadata, type(pd.DataFrame())):
        df = pd.read_csv(image_metadata)
    else:
        df = image_metadata

    df['urls'] = base_url + df[image_type_colum]
    urls, file_names = df['urls'], df[file_name_column]
    
    _thread_downloads(output_directory, urls, file_names)
    
    hipp.utils.optimize_geotifs(output_directory)
    
    return output_directory

def NAGAP_pre_select_images(image_metadata,
                            bounds=None,
                            roll=None,
                            year=None,
                            month=None,
                            day=None,
                            output_directory=None,
                            verbose=True):
    """
    bounds = (ULLON, ULLAT, LRLON, LRLAT)
    year   = 77 # e.g. for year 1977
    """
    print("Selecting images based on:")   
    
    if not isinstance(image_metadata, type(pd.DataFrame())):
        df = pd.read_csv(image_metadata, dtype=object)
    else:
        df = image_metadata

    df['Longitude'] = df['Longitude'].astype(float)
    df['Latitude'] = df['Latitude'].astype(float)
    
    if not isinstance(bounds,type(None)):
        print('bounds:', bounds)
        df = df[(df['Longitude']>bounds[0]) & 
                (df['Longitude']<bounds[2]) & 
                (df['Latitude']>bounds[3]) & 
                (df['Latitude']<bounds[1])]
    
    if not isinstance(roll,type(None)):
        print('roll:', roll)
        df = df[df['Roll'] == roll]
        
    if not isinstance(year,type(None)):
        print('year:', year)
        df = df[df['Year'] == str(year)]
        
    if not isinstance(month,type(None)):
        print('month:', month)
        df = df[df['Month'] == str(month).zfill(2)]
        
    if not isinstance(day,type(None)):
        print('day:', day)
        df = df[df['Day'] == str(day).zfill(2)]
        
    df = df.reset_index(drop=True)
    
    if len(list(set(df['Roll'].values))) > 1:
        print('NOTE: Filter results contain multiple camera rolls:')
        for i in sorted(list(set(df['Roll'].values))):
            print(i)
        
    if len(list(set(df['Year'].values))) > 1:
        print('NOTE: Filter results contain multiple years:')
        for i in sorted(list(set(df['Year'].values))):
            print(i)
            
    if len(list(set(df['Year'].values))) == 1 and len(list(set(df['Month'].values))) > 1:
        print('NOTE: Filter results contain multiple months:')
        for i in sorted(list(set(df['Month'].values))):
            print(i)
        
    if not isinstance(output_directory,type(None)):
        out = os.path.join(output_directory,'targets.csv')
        df.to_csv(out, index=False)
        return out
    
    else:
        return df
        
