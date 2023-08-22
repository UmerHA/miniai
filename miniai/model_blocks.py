# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/05_model_blocks.ipynb.

# %% auto 0
__all__ = ['conv']

# %% ../nbs/05_model_blocks.ipynb 2
import pickle,gzip,math,os,time,shutil,torch,matplotlib as mpl, numpy as np
import pandas as pd,matplotlib.pyplot as plt
from functools import partial
from pathlib import Path
from torch import tensor
from torch import nn

from torch.utils.data import DataLoader,default_collate
from typing import Mapping

from .datasets import *

# %% ../nbs/05_model_blocks.ipynb 8
def conv(ni, # Input filters
         nf, # Output filters
         ks=3, # Kernel size
         stride=2, # Stride,
         padding=None, # Padding
         act=nn.ReLU, # Activation
         norm=None, # Type of normalization layer to apply
         bias=None # Whether to apply bias
        )-> nn.Sequential:
    """ Generate a conv block with a conv layer and optional normalisation and activation. If bias 
    is None then the bias is not applied  to the conv if batch norm is used, otherwise it is

    Using ks=3 and padding=1 will result in the resolution reducing as per the stride, as will 
    ks=5 and padding=2

    Returns the block as a sequential model
    """
    if bias is None:
        bias = not norm in (torch.nn.modules.batchnorm.BatchNorm1d, 
                            torch.nn.modules.batchnorm.BatchNorm2d, 
                            torch.nn.modules.batchnorm.BatchNorm3d)
    if padding is None: padding=ks//2
    layers = [nn.Conv2d(ni, nf, stride=stride, kernel_size=ks, padding=padding, bias=bias)]
    if norm: layers.append(norm(nf))
    if act: layers.append(act())
    return nn.Sequential(*layers)

# %% ../nbs/05_model_blocks.ipynb 25
def _conv_block(ni, nf, stride, ks=3, act=act_gr, norm=None):
    """ Returns a block consisting of two conv blocks.  Note that the architectual choice being made 
    here is that the first conv changes the number of channels and the second keeps the number of 
    channels the same but reduces the resolution by using stride=2
    
    The pass through block uses a pooling layer to reduce the resolution and then a basic conv to change
    the number of channels to that required
    
    """
    return nn.Sequential(
        conv(ni, nf, stride=1, ks=ks, act=act, norm=norm),
        conv(nf, nf, stride=stride, ks=ks, act=None, norm=norm)
    )
