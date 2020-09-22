import cv2
import glob
import numpy as np
import os
import pandas as pd
import pathlib
from skimage import transform as tf

import hipp

def image_restitution(df_detected,
                      fiducial_coordinates_true_mm,
                      image_file_name_column_name = 'fileName',
                      scanning_resolution_mm = 0.02,
                      transform_coords = True,
                      transform_image = True,
                      crop_image = True,
                      output_shape = 10800,
                      interpolation_order = 3,
                      output_directory = 'input_data/preprocessed_images/',
                      qc = True):

    """
    Computes affine transformation between detected coordinates and true coordinates true, 
    then transforms image array.
                           
    The order of interpolation.
    0: Nearest-neighbor
    1: Bi-linear
    2: Bi-quadratic
    3: Bi-cubic
    4: Bi-quartic
    5: Bi-quintic
    """
                      
    # TODO add logging

    if transform_image or crop_image:
        p = pathlib.Path(output_directory)
        p.mkdir(parents=True, exist_ok=True)
    
    # QC lists
    coordinates_rmse_before_tform = []
    coordinates_rmse_after_tform = []
    coordinates_pp_dist_rmse_before_tform = []
    coordinates_pp_dist_rmse_after_tform = []
    midside_angle_diff_before_tform = []
    midside_angle_diff_after_tform = []
    corner_angle_diff_before_tform = []
    corner_angle_diff_after_tform = []
    qc_dataframes = []
    
    # convert true coordinates to image reference system
    fiducial_coordinates_true_mm = np.array(fiducial_coordinates_true_mm,dtype=float)
    fiducial_coordinates_true_px = fiducial_coordinates_true_mm / scanning_resolution_mm
    fiducial_coordinates_true_px[:,1] = fiducial_coordinates_true_px[:,1] * -1
    
    # prepare dataframe with detected coordinates
    df_coords = df_detected.drop(['fileName','principal_point_x','principal_point_y'], axis=1)
    
    for index, row in df_coords.iterrows():

        # convert coordinates to x,y order
        fiducial_coordinates      = np.array(list(zip(row.values[0::2], row.values[1::2])))
        fiducial_coordinates      = fiducial_coordinates[:,::-1] 

        # extract principal point
        principal_point = np.array((df_detected['principal_point_x'].iloc[index],
                                    df_detected['principal_point_y'].iloc[index]))

        # add prinicpal point to get true fiducial coordinates into image reference system
        fiducial_coordinates_true = fiducial_coordinates_true_px + principal_point


        if qc:
            # convert coordinates to camera reference system.
            fiducial_coordinates_mm, principal_point_mm = hipp.qc.convert_coordinates(fiducial_coordinates,
                                                                                      principal_point,
                                                                                      scanning_resolution_mm = scanning_resolution_mm)

            fiducial_coordinates_true_mm, _ = hipp.qc.convert_coordinates(fiducial_coordinates_true,
                                                                          principal_point,
                                                                          scanning_resolution_mm = scanning_resolution_mm)

            midside_coordinates_mm = fiducial_coordinates_mm[:4]
            corner_coordinates_mm = fiducial_coordinates_mm[4:]
            midside_coordinates_true_mm = fiducial_coordinates_true_mm[:4]
            corner_coordinates_true_mm = fiducial_coordinates_true_mm[4:]

            # compute RMSE for positions before transform.
            rmse = hipp.qc.compute_coordinate_rmse(fiducial_coordinates_mm, fiducial_coordinates_true_mm)
            coordinates_rmse_before_tform.append(rmse)

            # compute angular offsets for intersection angles at principal point before transform.
            diff = hipp.qc.compute_angle_diff(midside_coordinates_mm, midside_coordinates_true_mm)
            midside_angle_diff_before_tform.append(diff)
            diff = hipp.qc.compute_angle_diff(corner_coordinates_mm, corner_coordinates_true_mm)
            corner_angle_diff_before_tform.append(diff)

            # compute RMSE for distance between principal point and coordinates before transform.
            rmse = hipp.qc.compute_coordinate_distance_diff_rmse(midside_coordinates_mm,
                                                                 midside_coordinates_true_mm,
                                                                 corner_coordinates_mm,
                                                                 corner_coordinates_true_mm)
            coordinates_pp_dist_rmse_before_tform.append(rmse)


        if transform_image or crop_image:
            image_file = df_detected[image_file_name_column_name].iloc[index]
            image_array = cv2.imread(image_file, cv2.IMREAD_GRAYSCALE)

        if transform_image or transform_coords:
            # remove nan values
            fid_coord_tmp      = np.where(~np.isnan(fiducial_coordinates_true), fiducial_coordinates, np.nan)
            fid_coord_true_tmp = np.where(~np.isnan(fiducial_coordinates), fiducial_coordinates_true, np.nan)
            fid_coord_tmp      = np.array([x for x in fid_coord_tmp if ~np.isnan(x).any()], dtype=float)
            fid_coord_true_tmp = np.array([x for x in fid_coord_true_tmp if ~np.isnan(x).any()], dtype=float)

            # ensure at least 3 points are available to compute transform
            if len(fid_coord_tmp) >=3 and ~np.isnan(fid_coord_true_tmp).all():
                tform = tf.AffineTransform()
                tform.estimate(fid_coord_tmp, fid_coord_true_tmp)

                fiducial_coordinates_tform = tform(fiducial_coordinates)
                principal_point = tform(principal_point)[0]

                if transform_image:
                    # compute inverse transformation matrix
                    A = np.linalg.inv(tform.params)
                    image_array_transformed = tf.warp(image_array, A, output_shape=image_array.shape, order=interpolation_order)
                    image_array = (image_array_transformed*255).astype(np.uint8)

                if qc:
                    # convert transformed coordinates to camera reference system.
                    fiducial_coordinates_tform_mm, principal_point_tform_mm = hipp.qc.convert_coordinates(fiducial_coordinates_tform,
                                                                                              principal_point,
                                                                                              scanning_resolution_mm=scanning_resolution_mm)

                    midside_coordinates_tform_mm = fiducial_coordinates_tform_mm[:4]
                    corner_coordinates_tform_mm = fiducial_coordinates_tform_mm[4:]

                    # compute RMSE for positions after transform.
                    rmse = hipp.qc.compute_coordinate_rmse(fiducial_coordinates_tform_mm, fiducial_coordinates_true_mm)
                    coordinates_rmse_after_tform.append(rmse)


                    # compute angular offsets for intersection angles at principal point after transform.
                    diff = hipp.qc.compute_angle_diff(midside_coordinates_tform_mm, midside_coordinates_true_mm)
                    midside_angle_diff_after_tform.append(diff)
                    diff = hipp.qc.compute_angle_diff(corner_coordinates_tform_mm, corner_coordinates_true_mm)
                    corner_angle_diff_after_tform.append(diff)

                    # compute RMSE for distance between principal point and coordinates after transform.
                    rmse = hipp.qc.compute_coordinate_distance_diff_rmse(midside_coordinates_tform_mm,
                                                                         midside_coordinates_true_mm,
                                                                         corner_coordinates_tform_mm,
                                                                         corner_coordinates_true_mm)
                    coordinates_pp_dist_rmse_after_tform.append(rmse)



        if crop_image:
            # print('here')
            principal_point = np.array([int(round(x)) for x in principal_point])
            image_array = hipp.image.crop_about_point(image_array,
                                                      principal_point[::-1], # requires y,x order
                                                      output_shape = output_shape)
            path, basename, extension = hipp.io.split_file(image_file)
            out = os.path.join(output_directory,basename+extension)
            cv2.imwrite(out,image_array)
            print(out)

        elif transform_image:
            path, basename, extension = hipp.io.split_file(image_file)
            out = os.path.join(output_directory,basename+extension)
            cv2.imwrite(out,image_array)
            
    if qc:
        qc_dataframes = []

        qc_dataframes.append(pd.DataFrame(list(df_detected[image_file_name_column_name].values),
                                          columns=[image_file_name_column_name]))
        qc_dataframes.append(pd.DataFrame(coordinates_rmse_before_tform,
                                          columns=['coordinates_rmse_before_tform']))
        qc_dataframes.append(pd.DataFrame(coordinates_pp_dist_rmse_before_tform,
                                          columns=['coordinates_pp_dist_rmse_before_tform']))
        qc_dataframes.append(pd.DataFrame(midside_angle_diff_before_tform,
                                          columns=['midside_angle_diff_before_tform']))
        qc_dataframes.append(pd.DataFrame(corner_angle_diff_before_tform,
                                          columns=['corner_angle_diff_before_tform']))
        if transform_coords:
            qc_dataframes.append(pd.DataFrame(coordinates_rmse_after_tform,
                                              columns=['coordinates_rmse_after_tform']))
            qc_dataframes.append(pd.DataFrame(coordinates_pp_dist_rmse_after_tform,
                                              columns=['coordinates_pp_dist_rmse_after_tform']))
            qc_dataframes.append(pd.DataFrame(midside_angle_diff_after_tform,
                                              columns=['midside_angle_diff_after_tform']))
            qc_dataframes.append(pd.DataFrame(corner_angle_diff_after_tform,
                                              columns=['corner_angle_diff_after_tform']))
            
            qc_df = pd.concat(qc_dataframes,axis=1)
            qc_df.index = qc_df[image_file_name_column_name].str[-12:-4]
            
            hipp.plot.plot_restitution_qc(qc_df)
        
def iter_detect_fiducials(image_files_directory = 'input_data/raw_images/',
                          image_file_name_column_name = 'fileName',
                          image_files_extension ='.tif',
                          template_file = None,
                          template_high_res_zoomed_file = None,
                          midside_fiducials=False,
                          corner_fiducials=False,
                          qc=True):
    
    """
    Function to iteratively detect fiducial markers in a set of images and return as pandas.DataFrame.
                           
    Ensure that the templates correspond to either the fiducial markers at the midside or corners. 
    Specify flag accordingly.
    """
    
    images = sorted(glob.glob(os.path.join(image_files_directory,'*'+image_files_extension)))
    template_array = cv2.imread(template_file,cv2.IMREAD_GRAYSCALE)
    fiducial_locations = []
    intersection_angles = []
    principal_points = []
    quality_scores = []
    
    for image_file in images:
        image_array = cv2.imread(image_file,cv2.IMREAD_GRAYSCALE)
        
        # Subset image array into window slices to speed up template matching
        if midside_fiducials:
            windows = hipp.core.define_midside_windows(image_array)
        elif corner_fiducials:
            windows = hipp.core.define_corner_windows(image_array)
        else:
            print("Please specify midside or corner fiducials and provide corresponding templates.")
            break
        
        slices = hipp.core.slice_image_frame(image_array,windows)
        
        # Detect fiducial in each window
        matches, _ = hipp.core.detect_fiducials(slices,
                                                template_array,
                                                windows)
        
        if midside_fiducials:
            labels = ['midside_left','midside_top','midside_right','midside_bottom']
        elif corner_fiducials:
            labels = ['corner_top_left','corner_top_right','corner_bottom_right','corner_bottom_left']
        quality_score_labels = [sub + '_score' for sub in labels]

        subpixel_fiducial_locations, subpixel_quality_scores = hipp.core.detect_subpixel_fiducial_coordinates(image_file,
                                                                image_array,
                                                                matches,
                                                                template_high_res_zoomed_file,
                                                                labels=labels,
                                                                qc=qc)
                          
        fiducial_locations.append(subpixel_fiducial_locations)
        quality_scores.append(subpixel_quality_scores)
    
    

    images_df = pd.DataFrame(images,columns=[image_file_name_column_name])
    fiducial_locations_df = pd.DataFrame(fiducial_locations,columns=labels)
    quality_scores_df = pd.DataFrame(quality_scores, columns=quality_score_labels)
    principal_points_df = hipp.core.compute_principal_points(fiducial_locations_df, 
                                                             quality_scores_df)
    df  = pd.concat([images_df,
                     fiducial_locations_df,
                     quality_scores_df,
                     principal_points_df],
                     axis=1)
    return df