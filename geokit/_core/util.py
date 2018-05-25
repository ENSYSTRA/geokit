'''The Util sub-module contains a number of generally helpful utillity functions, classes, and constants. It is also used for common imports across all GeoKit functionality'''

import os, sys, re
import numpy as np
import gdal, ogr, osr
from tempfile import TemporaryDirectory, NamedTemporaryFile
from glob import glob
import warnings
from collections import namedtuple, Iterable, defaultdict
import pandas as pd
from scipy.stats import describe
from scipy.interpolate import RectBivariateSpline
from types import GeneratorType

######################################################################################
# test modules

# The main SRS for lat/lon coordinates
_test = osr.SpatialReference()
res = _test.ImportFromEPSG(4326)

# Quick check if gdal loaded properly
if(not res==0 ):
    raise RuntimeError("GDAL did not load properly. Check your 'GDAL_DATA' environment variable")

######################################################################################
# An few errors just for me!
class GeoKitError(Exception): pass
class GeoKitSRSError(GeoKitError): pass
class GeoKitGeomError(GeoKitError): pass
class GeoKitLocationError(GeoKitError): pass
class GeoKitRasterError(GeoKitError): pass
class GeoKitVectorError(GeoKitError): pass
class GeoKitExtentError(GeoKitError): pass
class GeoKitRegionMaskError(GeoKitError): pass

#####################################################################
# Testers

def isVector(source): 
    """
    Test if loadVector fails for the given input

    Parameters:
    -----------
    source : str
        The path to the vector file to load

    Returns:
    --------
    bool -> True if the given input is a vector

    """
    
    if isinstance(source, gdal.Dataset): 
        if source.GetLayerCount() > 0: return True
        else: return False
    elif isinstance(source, str):
        d = gdal.IdentifyDriver(source)

        meta = d.GetMetadata()
        if meta.get("DCAP_VECTOR", False)=="YES": return True
        else: return False
    else:
        return False

def isRaster(source): 
    """
    Test if loadRaster fails for the given input

    Parameters:
    -----------
    source : str
        The path to the raster file to load

    Returns:
    --------
    bool -> True if the given input is a raster

    """
    if isinstance(source, gdal.Dataset): 
        try:
            if source.GetLayerCount() == 0: return True # This should always be true?
            else: return False
        except:
            return False
    elif isinstance(source, str):
        d = gdal.IdentifyDriver(source)

        meta = d.GetMetadata()
        if meta.get("DCAP_RASTER", False)=="YES": return True
        else: return False
    else:
        return False


##################################################################
# General funcs
# matrix scaler
def scaleMatrix(mat, scale, strict=True):
    """Scale a 2-dimensional matrix. For example, a 2x2 matrix, with a scale of 2, 
    will become a 4x4 matrix. Or scaling a 24x24 matrix with a scale of -3 will 
    produce an 8x8 matrix.

    * Scaling UP (positive) results in a dimensionally larger matrix where each 
      value is repeated scale^2 times
    * scaling DOWN (negative) results in a dimensionally smaller matrix where each 
      value is the average of the associated 'up-scaled' block

    Parameters:
    -----------
        mat : numpy.ndarray or [[numeric,],] 
            The data to be scaled
              * Must be two dimensional
        
        scale : int or (int, int)
            The dimensional scaling factor for either both, or independently for
            the Y and X dimensions
              * If scaling down, the scaling factors must be a factor of the their 
                associated dimension in the input matrix (unless 'strict' is set 
                to False)
        
        strict : bool 
            Whether or not to force a fail when scaling-down by a scaling factor 
            which is not a dimensional factor
              * Really intended for internal use...
              * When scaling down by a non-dimensional factor, the matrix will be 
                padded with zeros such that the new matrix has dimensional sizes 
                which are divisible by the scaling factor. The points which are 
                not at the right or bottom boundary are averaged, same as before. 
                The points which lie on the edge however, are also averaged across 
                all the values which lie in those pixels, but they are corrected 
                so that the averaging does NOT take into account the padded zeros.

    Returns:
    --------

    numpy.ndarray
    

    Examples:
    ---------

    INPUT       Scaling Factor      Output
    -----       --------------      ------

    | 1 2 |             2           | 1 1 2 2 |
    | 3 4 |                         | 1 1 2 2 |
                                    | 3 3 4 4 |
                                    | 3 3 4 4 |


    | 1 1 1 1 |        -2           | 1.5  2.0 | 
    | 2 2 3 3 |                     | 5.25 6.75|
    | 4 4 5 5 |
    | 6 7 8 9 |


    | 1 1 1 1 |        -3           | 2.55  3.0 |
    | 2 2 3 3 |   * strict=False    | 7.0    9  |
    | 4 4 5 5 |                       
    | 6 7 8 9 |       *padded*          
                    -------------
                   | 1 1 1 1 0 0 |
                   | 2 2 3 3 0 0 |
                   | 4 4 5 5 0 0 |
                   | 6 7 8 9 0 0 |
                   | 0 0 0 0 0 0 |
                   | 0 0 0 0 0 0 |

    """

    # unpack scale
    try:
        yScale,xScale = scale
    except:
        yScale,xScale = scale, scale

    # check for ints
    if( not (isinstance(xScale,int) and isinstance(yScale,int))):
        raise ValueError("scale must be integer types")

    if (xScale==0 and yScale==0): return mat # no scaling (it would just be silly to call this)
    elif (xScale>0 and yScale>0): # scale up
        out = np.zeros((mat.shape[0]*yScale, mat.shape[1]*xScale), dtype=mat.dtype)
        for yo in range(yScale):
            for xo in range(xScale):
                out[yo::yScale, xo::xScale] = mat
    
    elif (xScale<0 and yScale<0): # scale down
        xScale = -1*xScale
        yScale = -1*yScale
        # ensure scale is a factor of both xSize and ySize
        if strict:
            if( not( mat.shape[0]%yScale==0 and mat.shape[1]%xScale==0)):
                raise GeoKitError("Matrix can only be scaled down by a factor of it's dimensions")
            yPad = 0
            xPad = 0
        else:
            yPad = yScale-mat.shape[0]%yScale # get the amount to pad in the y direction
            xPad = xScale-mat.shape[1]%xScale # get the amount to pad in the x direction
            
            if yPad==yScale: yPad=0
            if xPad==xScale: xPad=0

            # Do y-padding
            if yPad>0: mat = np.concatenate( (mat, np.zeros((yPad,mat.shape[1])) ), 0)
            if xPad>0: mat = np.concatenate( (mat, np.zeros((mat.shape[0],xPad)) ), 1)
        
        out = np.zeros((mat.shape[0]//yScale, mat.shape[1]//xScale), dtype="float")
        for yo in range(yScale):
            for xo in range(xScale):
                out += mat[yo::yScale, xo::xScale]
        out = out/(xScale*yScale)

        # Correct the edges if a padding was provided
        if yPad>0: out[:-1,-1] *= yScale/(yScale-yPad) # fix the right edge EXCLUDING the bot-left point
        if xPad>0: out[-1,:-1] *= xScale/(xScale-xPad) # fix the bottom edge EXCLUDING the bot-left point
        if yPad>0: out[-1,-1]  *= yScale*xScale/(yScale-yPad)/(xScale-xPad) # fix the bot-left point

    else: # we have both a scaleup and a scale down
        raise GeoKitError("Dimensions must be scaled in the same direction")

    return out

# A predefined kernel processor for use in mutateRaster
def KernelProcessor(size, edgeValue=0, outputType=None, passIndex=False):
    """A decorator which automates the production of kernel processors for use 
    in mutateRaster (although it could really used for processing any matrix)
    
    Parameters:
    -----------
    size : int
        The number of pixels to expand around a center pixel
        * A 'size' of 0 would make a processing matrix with size 1x1. As in, 
          just the value at each point. This would be silly to call...
        * A 'size' of 1 would make a processing matrix of size 3x3. As in, one 
          pixel around the center pixel in all directions
        * Processed matrix size is equal to 2*size+1 

    edgeValue : numeric; optional
        The value to apply to the edges of the matrix before applying the kernel
        * Will be factored into the kernelling when processing near the edges

    outputType : np.dtype; optional
        The datatype of the processed values 
        * Only useful if the output type of the kerneling step is different from
          the matrix input type

    passIndex : bool
        Whether or not to pass the x and y index to the processing function
        * If True, the decorated function must accept an input called 'xi' and 
          'yi' in addition to the matrix
        * The xi and yi correspond to the index of the center pixel in the 
          original matrix
    
    Returns:
    --------
    function

    Example:
    --------
    * Say we want to make a processor which calculates the average of pixels 
      which are within a distance of 2 indcies. In other words, we want the 
      average of a 5x5 matrix centered around each pixel.
    * Assume that we can use the value -9999 as a no data value

    >>>  @KernelProcessor(2, edgeValue=-9999)
    >>>  def getMean( mat ):
    >>>      # Get only good values
    >>>      goodValues = mat[mat!=-9999]
    >>>      
    >>>      # Return the mean
    >>>      return goodValues.mean()

    """
    def wrapper1(kernel):
        def wrapper2(matrix):
            # get the original matrix sizes
            yN, xN = matrix.shape

            # make a padded version of the matrix
            paddedMatrix = np.ones((yN+2*size,xN+2*size), dtype=matrix.dtype)*edgeValue
            paddedMatrix[size:-size,size:-size] = matrix

            # apply kernel to each pixel
            output = np.zeros((yN,xN), dtype = matrix.dtype if outputType is None else outputType)
            for yi in range(yN):
                for xi in range(xN):
                    slicedMatrix = paddedMatrix[yi:2*size+yi+1, xi:2*size+xi+1]
                    
                    if passIndex: output[yi,xi] = kernel(slicedMatrix, xi=xi, yi=yi)
                    else: output[yi,xi] = kernel(slicedMatrix)

            # done!
            return output
        return wrapper2
    return wrapper1

#############################################################
## internal use source generators


def quickVector(geom, output=None):
    """GeoKit internal for quickly creating a vector datasource"""
    ######## Create a quick vector source
    if output:
        driver = gdal.GetDriverByName("ESRI Shapefile")
        dataSource = driver.Create( output, 0,0 )
    else:
        driver = gdal.GetDriverByName("Memory")
        dataSource = driver.Create( "", 0, 0, 0, gdal.GDT_Unknown)
        
    # Create the layer and write feature
    layer = dataSource.CreateLayer( "", geom.GetSpatialReference(), geom.GetGeometryType() )
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry( geom )

    # Create the feature
    layer.CreateFeature( feature )
    feature.Destroy()

    # Done!
    if output: return output
    else: return dataSource


def quickRaster(bounds, srs, dx, dy, dType="GDT_Byte", noData=None, fill=None, data=None):
    """GeoKit internal for quickly creating a raster datasource"""
    try:
        xMin, yMin, xMax, yMax = bounds
    except TypeError:
        xMin, yMin, xMax, yMax = bounds.xyXY
        srs = bounds.srs
    
    ## Make a raster dataset and pull the band/maskBand objects
    # fix origins to multiples of the resolutions
    ## This first way behaves more like gdalwarp/rasterize, but it adds pixel when they shouldn't be
    # originX = float(np.floor(xMin/dx)*dx)
    # originY = float(np.ceil(yMax/dy)*dy) # Always use the "Y-at-Top" orientation

    # cols = int(np.ceil((xMax-originX)/dx)) 
    # rows = int(np.ceil((originY-yMin)/abs(dy)))

    # Old way, which doesn't seem to agree with gdal warping behavior, but doesn't cause so many issues
    originX = float(np.round(xMin/dx)*dx)
    originY = float(np.round(yMax/dy)*dy) # Always use the "Y-at-Top" orientation

    cols = int(round((xMax-originX)/dx)) 
    rows = int(round((originY-yMin)/abs(dy)))
    
    # Open the driver
    driver = gdal.GetDriverByName('Mem') # create a raster in memory
    raster = driver.Create('', cols, rows, 1, getattr(gdal,dType))

    if(raster is None):
        raise GeoKitError("Failed to create temporary raster")

    raster.SetGeoTransform((originX, abs(dx), 0, originY, 0, -1*abs(dy)))
    
    # Set the SRS
    raster.SetProjection( srs.ExportToWkt() )
    
    # get the band
    band = raster.GetRasterBand(1)

    # set nodata
    if not noData is None: 
        band.SetNoDataValue(noData)
        if fill is None and data is None: 
            band.Fill(noData)

    # do fill
    if not fill is None: band.Fill(fill)

    # add data
    if not data is None: 
        band.WriteArray(data)
    band.FlushCache()
    
    # Done!
    del band
    raster.FlushCache()
    return raster


### Helpful classes
Feature = namedtuple("Feature", "geom attr")

### Image plotter
def drawImage(data, bounds=None, ax=None, scaling=None, yAtTop=True, cbar=False, **kwargs):
    """Draw a matrix as an image on a matplotlib canvas

    Inputs:
        data : The data to plot as a 2D matrix
            - numpy.ndarray

        bounds : The spatial context of the matrix's boundaries
            - (xMin, yMin, xMax, yMax)
            - geokit.Extent object
            * If bounds is None, the plotted matrix will be bounded by the matrix's dimension sizes

        ax : An optional matplotlib axes to plot on
            * If ax is None, the function will draw and create its own axis

        scaling - int : An optional scaling factor used to scale down the data matrix
            * Used to decrease strain on the system's resources for visualing the data
            * make sure to use a NEGATIVE integer to scale down (positive will scale up and make a larger matrix)

        yAtTop - True/False : Flag indicating that the data is in the typical y-index-starts-at-top orientation
            * If False, the data matrix will be flipped before plotting

        cbar - True/False : Flag indicating whether or not to automatically add a colorbar
            * Only operates when an axis has not been given

        **kwargs : Passed on to a call to matplotlib's imshow function
            * Determines the visual characteristics of the drawn image

    """
    showPlot = False
    if ax is None:
        showPlot = True
        import matplotlib.pyplot as plt
        plt.figure(figsize=(12,12))
        ax = plt.subplot(111)

    # If bounds is none, make a boundary
    if bounds is None:
        xMin,yMin,xMax,yMax = 0,0,data.shape[1],data.shape[0] # bounds = xMin,yMin,xMax,yMax
    else:
        try:
            xMin,yMin,xMax,yMax = bounds
        except: # maybe bounds is an ExtentObject
            xMin,yMin,xMax,yMax = bounds.xyXY

    # Set extentdraw
    extent = (xMin,xMax,yMin,yMax)
    
    # handle flipped data
    if not yAtTop: data=data[::-1,:]

    # Draw image
    if scaling: data=scaleMatrix(data,scaling,strict=False)
    h = ax.imshow( data, extent=extent, **kwargs)

    # Done!
    if showPlot:
        if cbar: plt.colorbar(h)

        ax.set_aspect('equal')
        ax.autoscale(enable=True)
        
        plt.show()
    else:
        return h