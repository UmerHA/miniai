# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/05_model_blocks.ipynb.

# %% auto 0
__all__ = ['act_gr', 'GeneralRelu', 'conv', 'ResBlock', 'pre_conv', 'lin', 'SelfAttention', 'SelfAttention2D', 'EmbResBlock',
           'saved', 'DownBlock', 'UpBlock', 'EmbUNetModel']

# %% ../nbs/05_model_blocks.ipynb 2
import pickle,gzip,math,os,time,shutil,torch,matplotlib as mpl, numpy as np
import pandas as pd,matplotlib.pyplot as plt
from functools import partial, wraps
from pathlib import Path
from torch import tensor
from torch import nn
import fastcore.test as fct

from torch.utils.data import DataLoader,default_collate
from typing import Mapping

from .datasets import *

# %% ../nbs/05_model_blocks.ipynb 4
# Temp - to be removed once activations module in place
class GeneralRelu(nn.Module):
    def __init__(self, leak=None, sub=None, maxv=None):
        super().__init__()
        self.leak, self.sub, self. maxv = leak, sub, maxv
        
    def forward(self, x):
        x = F.leaky_relu(x, self.leak) if self.leak is not None else F.relu(x)
        if self.sub is not None: x -= self.sub
        if self.maxv is not None: x = x.clamp_max_(self.maxv)
        return x

# %% ../nbs/05_model_blocks.ipynb 5
# Temp - to be removed once activations module in place
act_gr = partial(GeneralRelu, leak=0.1, sub=0.4)

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

# %% ../nbs/05_model_blocks.ipynb 26
def _conv_block(ni, # input channels
                nf, # out channels
                stride, # stride
                ks=3, # kernel size
                act=act_gr, # activation to use
                norm=None # normalization to use
               ):
    """ Generates a sequential model consisting of two conv blocks.  Note that the architectual 
    choice being made here is that the first conv changes the number of channels and the second 
    keeps the number of channels the same but reduces the resolution by using stride=2

    """
    return nn.Sequential(
        conv(ni, nf, stride=1, ks=ks, act=act, norm=norm),
        conv(nf, nf, stride=stride, ks=ks, act=None, norm=norm)
    )

# %% ../nbs/05_model_blocks.ipynb 27
class ResBlock(nn.Module):
    """ Create a traditional Resnet block with a conv block, a pass through path, a pooling layer and
    an activation.
  
    The pass through block uses a pooling layer to reduce the resolution if required and then a 
    basic conv to change the number of channels to that required to facilitate addition to the 
    conv block output

    The forward method will feed data though the block
    """
    
    def __init__(self, 
                 ni, # input channels
                 nf, # out channels
                 stride=1, # stride
                 ks=3, # kernel size
                 padding=None, # padding
                 act=act_gr, # activation to use
                 norm=None # normalization to use
                ):
        super().__init__()
        # Create the two convolution layers
        self.convs = _conv_block(ni, nf, stride, ks=ks, act=act, norm=norm)
        # Create the pass through layer.  Note that this can only be a complete pass of the input if ni=nf.
        # Where this is not the case a single conv is used (with no activation and kernel size of 1)
        self.idconv = fc.noop if ni==nf else conv(ni, nf, stride=1, ks=1, act=None)
        self.pool = fc.noop if stride==1 else nn.AvgPool2d(kernel_size=2, ceil_mode=True)
        self.act = act()
        
    def forward(self, x):
        return self.act(self.convs(x) + self.idconv(self.pool(x)))

# %% ../nbs/05_model_blocks.ipynb 29
def pre_conv(ni, # input channels
             nf, # out channels
             ks=3, # kernel size
             stride=1, # stride
             act=nn.SiLU, # activation to use
             norm=None, # normalization to use
             bias=True # whether to use bias for the conv layer
            ):
    """ Generate a conv block with a conv layer and optional normalisation and activation.
    Bias and norm layers are optional. Using ks=3 and padding=1 will result in the resolution 
    reducing as per the stride, as will ks=5 and padding=2

    Returns the block as a sequential model
    """
    layers = nn.Sequential()
    if norm: layers.append(norm(ni))
    if act : layers.append(act())
    layers.append(nn.Conv2d(ni, nf, stride=stride, kernel_size=ks, padding=ks//2, bias=bias))
    return layers

# %% ../nbs/05_model_blocks.ipynb 35
def lin(ni, #input channels
        nf, #output channels"
        act=nn.SiLU, # activation to use or None
        norm=None, # normalisation to use or None
        bias=True, # Whether to use bias in the linear layer
       ):
    """ Create a sequential model of a linear layer with optional bias and optional normalization and activation layers
    """
    layers = nn.Sequential()
    if norm: layers.append(norm(ni))
    if act : layers.append(act())
    layers.append(nn.Linear(ni, nf, bias=bias))
    return layers

# %% ../nbs/05_model_blocks.ipynb 37
class SelfAttention(nn.Module):
    def __init__(self, ni, attn_chans, transpose=True):
        super().__init__()
        self.nheads = ni//attn_chans
        self.scale = math.sqrt(ni/self.nheads)
        self.norm = nn.LayerNorm(ni)
        self.qkv = nn.Linear(ni, ni*3)
        self.proj = nn.Linear(ni, ni)
        self.t = transpose
    
    def forward(self, x):
        n,c,s = x.shape
        if self.t: x = x.transpose(1, 2)
        x = self.norm(x)
        x = self.qkv(x)
        x = rearrange(x, 'n s (h d) -> (n h) s d', h=self.nheads)
        q,k,v = torch.chunk(x, 3, dim=-1)
        s = (q@k.transpose(1,2))/self.scale
        x = s.softmax(dim=-1)@v
        x = rearrange(x, '(n h) s d -> n s (h d)', h=self.nheads)
        x = self.proj(x)
        if self.t: x = x.transpose(1, 2)
        return x

# %% ../nbs/05_model_blocks.ipynb 40
class SelfAttention2D(SelfAttention):
    def forward(self, x):
        n,c,h,w = x.shape
        return super().forward(x.view(n, c, -1)).reshape(n,c,h,w)

# %% ../nbs/05_model_blocks.ipynb 42
class EmbResBlock(nn.Module):
    def __init__(self, n_emb, ni, nf=None, ks=3, act=nn.SiLU, norm=nn.BatchNorm2d, attn_chans=0):
        super().__init__()
        if nf is None: nf = ni
        self.emb_proj = nn.Linear(n_emb, nf*2)
        self.conv1 = pre_conv(ni, nf, ks, act=act, norm=norm)
        self.conv2 = pre_conv(nf, nf, ks, act=act, norm=norm)
        self.idconv = fc.noop if ni==nf else nn.Conv2d(ni, nf, 1)
        self.attn = False
        if attn_chans: self.attn = SelfAttention2D(nf, attn_chans)

    def forward(self, x, t):
        inp = x
        x = self.conv1(x)
        emb = self.emb_proj(F.silu(t))[:, :, None, None]
        scale,shift = torch.chunk(emb, 2, dim=1)
        x = x*(1+scale) + shift
        x = self.conv2(x)
        x = x + self.idconv(inp)
        if self.attn: x = x + self.attn(x)
        return x

# %% ../nbs/05_model_blocks.ipynb 44
def saved(m, # torch.nn.module, the module for which the output will be saved
          blk # The block containing the module
         ):
    """Creates a function that will save the values of the embedding layers to facilitate passing to the 
    decoding part.  Depends upon the calling block containing a 'saved" attribute as a list. Each module in the block 
    for which this is called will have its exit activations saved in the list

    The wraps library simply ensures that any documentation of the wrapped method is available to the parent
    """
    m_ = m.forward

    @wraps(m.forward)
    def _f(*args, **kwargs):
        res = m_(*args, **kwargs)
        blk.saved.append(res)
        return res

    m.forward = _f
    return m

# %% ../nbs/05_model_blocks.ipynb 53
class DownBlock(nn.Module):
    """ A down block is a part of a stable diffusion Unet.  It contains an EmbResBlock which is followed 
    by an optional down block (if no down block then an identity is used).  Activations of teh EmbResBlock
    and the down block are saved for use as cross connections for the corresponding up blocks
    """
    def __init__(self, n_emb, ni, nf, add_down=True, num_layers=1, attn_chans=0):
        super().__init__()
        self.resnets = nn.ModuleList([saved(EmbResBlock(n_emb, ni if i==0 else nf, nf, attn_chans=attn_chans), self)
                                      for i in range(num_layers)])
        self.down = saved(nn.Conv2d(nf, nf, 3, stride=2, padding=1), self) if add_down else nn.Identity()

    def forward(self, x, t):
        self.saved = []
        for resnet in self.resnets: x = resnet(x, t)
        x = self.down(x)
        return x

# %% ../nbs/05_model_blocks.ipynb 54
class UpBlock(nn.Module):
    def __init__(self, n_emb, ni, prev_nf, nf, add_up=True, num_layers=2, attn_chans=0):
        super().__init__()
        self.resnets = nn.ModuleList(
            [EmbResBlock(n_emb, (prev_nf if i==0 else nf)+(ni if (i==num_layers-1) else nf), nf, attn_chans=attn_chans)
            for i in range(num_layers)])
        self.up = upsample(nf) if add_up else nn.Identity()

    def forward(self, x, t, ups):
        for resnet in self.resnets: x = resnet(torch.cat([x, ups.pop()], dim=1), t)
        return self.up(x)

# %% ../nbs/05_model_blocks.ipynb 55
class EmbUNetModel(nn.Module):
    def __init__( self, in_channels=3, out_channels=3, nfs=(224,448,672,896), num_layers=1, attn_chans=8, attn_start=1):
        super().__init__()
        self.conv_in = nn.Conv2d(in_channels, nfs[0], kernel_size=3, padding=1)
        self.n_temb = nf = nfs[0]
        n_emb = nf*4
        self.emb_mlp = nn.Sequential(lin(self.n_temb, n_emb, norm=nn.BatchNorm1d),
                                     lin(n_emb, n_emb))
        self.downs = nn.ModuleList()
        n = len(nfs)
        for i in range(n):
            ni = nf
            nf = nfs[i]
            self.downs.append(DownBlock(n_emb, ni, nf, add_down=i!=n-1, num_layers=num_layers,
                                        attn_chans=0 if i<attn_start else attn_chans))
        self.mid_block = EmbResBlock(n_emb, nfs[-1])

        rev_nfs = list(reversed(nfs))
        nf = rev_nfs[0]
        self.ups = nn.ModuleList()
        for i in range(n):
            prev_nf = nf
            nf = rev_nfs[i]
            ni = rev_nfs[min(i+1, len(nfs)-1)]
            self.ups.append(UpBlock(n_emb, ni, prev_nf, nf, add_up=i!=n-1, num_layers=num_layers+1,
                                    attn_chans=0 if i>=n-attn_start else attn_chans))
        self.conv_out = pre_conv(nfs[0], out_channels, act=nn.SiLU, norm=nn.BatchNorm2d, bias=False)

    def forward(self, inp):
        x,t = inp
        temb = timestep_embedding(t, self.n_temb)
        emb = self.emb_mlp(temb)
        x = self.conv_in(x)
        saved = [x]
        for block in self.downs: x = block(x, emb)
        saved += [p for o in self.downs for p in o.saved]
        x = self.mid_block(x, emb)
        for block in self.ups: x = block(x, emb, saved)
        return self.conv_out(x)
