"""
Keras implementation of CapsNet in Hinton's paper Dynamic Routing Between Capsules.
The current version maybe only works for TensorFlow backend. Actually it will be straightforward to re-write to TF code.
Adopting to other backends should be easy, but I have not tested this. 

Usage:
       python capsulenet.py
       python capsulenet.py --epochs 50
       python capsulenet.py --epochs 50 --routings 3
       ... ...
    
Modified by: Ruben Hwasser, Author: Xifeng Guo, Github: `https://github.com/XifengGuo/CapsNet-Keras`
"""

import numpy as np
from keras import layers, models, optimizers
from keras import backend as K
from keras.utils import to_categorical
from keras.layers import BatchNormalization, concatenate, Flatten, ReLU, Dense, Dropout, Conv2D, MaxPooling2D
import matplotlib.pyplot as plt
from PIL import Image
from utils import margin_loss, data_from_csv, read_images, data_from_csv_nonimage, read_data
from capsulelayers import CapsuleLayer, PrimaryCap, Length, Mask
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import scale
from sklearn.metrics import confusion_matrix, classification_report
import sys
K.set_image_data_format('channels_last')

# import wandb
# from wandb.keras import WandbCallback
id                  = '#1'
DIM                 = '10x10'
CONSTRUCTION_METHOD = 'image' # 'image' or 'matrix'
RUN_NAME            = 'CapsNet_image_id-' + id + '_' + DIM
ADD_COMMENT         = 'w30'
nMEASUREMENTS       = '1,000'
COMMENTS            = 'comments here' + ADD_COMMENT
NUMBER_OF_CLASSES   = 6
tag                 = '6class'
csv_filepath        = 'data/train_labels_' + tag + '.txt'
data_filepath       = 'data/train/complexbaseband/10x10_' + tag + '/'

def create_layers(input_img, n_class, routings):
    # Layer 1: Just a conventional Conv2D layer
    conv1 = layers.Conv2D(filters=128, kernel_size=5, strides=1, padding='valid', activation='relu')(input_img)

    # Layer 2: Conv2D layer with `squash` activation, then reshape to [None, num_capsule, dim_capsule]
    primarycaps = PrimaryCap(conv1, dim_capsule=8, n_channels=12, kernel_size=5, strides=2, padding='valid')

    # Layer 3: Capsule layer. Routing algorithm works here.
    digitcaps = CapsuleLayer(num_capsule=n_class, dim_capsule=4, routings=routings)(primarycaps)

    return digitcaps

def CapsNet(input_shape, n_class, routings):
    """
    A Capsule Network.
    :param input_shape: data shape, 3d, [width, height, channels]
    :param n_class: number of classes
    :param routings: number of routing iterations
    :return: Two Keras Models, the first one used for training, and the second one for evaluation.
            `eval_model` can also be used for training.
    """
    channelb_input = layers.Input(shape=input_shape)
    channelc_input = layers.Input(shape=input_shape)
    channeld_input = layers.Input(shape=input_shape)

    channelb_model = create_layers(channelb_input, n_class, routings)
    channelc_model = create_layers(channelc_input, n_class, routings)
    channeld_model = create_layers(channeld_input, n_class, routings)
    conv = concatenate([channelb_model, channelc_model, channeld_model])
    dense = Dense(512, use_bias=True)(conv)
    dense = ReLU()(dense)
    dense = Dropout(0.4)(dense)
    dense = Dense(1024, use_bias=True)(dense)
    dense = ReLU()(dense)

    out_caps = Length(name='capsnet')(dense)

    # Models for training and evaluation (prediction)
    train_model = models.Model([channelb_input, channelc_input, channeld_input], out_caps)
    eval_model = models.Model([channelb_input, channelc_input, channeld_input], out_caps)

    return train_model, eval_model

def train(model, data, args):
    """
    Training a CapsuleNet
    :param model: the CapsuleNet model
    :param data: a tuple containing training and testing data, like `((x_train, y_train), (x_test, y_test))`
    :param args: arguments
    :return: The trained model
    """
    # wandb.init(name=RUN_NAME, project="6_class", notes=COMMENTS)

    # unpacking the data
    ([x_train_channelb, x_train_channelc, x_train_channeld], y_train), ([x_test_channelb, x_test_channelc, x_test_channeld], y_test) = data

    # callbacks
    log = callbacks.CSVLogger(args.save_dir + '/log.csv')
    tb = callbacks.TensorBoard(log_dir=args.save_dir + '/tensorboard-logs',
                               batch_size=args.batch_size, histogram_freq=int(args.debug))
    checkpoint = callbacks.ModelCheckpoint(args.save_dir + '/weights-{epoch:02d}.h5', monitor='val_acc',
                                           save_best_only=True, save_weights_only=True, verbose=1)
    lr_decay = callbacks.LearningRateScheduler(schedule=lambda epoch: args.lr * (args.lr_decay ** epoch))

    # compile the model
    model.compile(optimizer=optimizers.Adam(lr=args.lr),
                  loss=[margin_loss],
                  loss_weights=[1.],
                  metrics={'capsnet': 'accuracy'})

    model.fit([x_train_channelb, x_train_channelc, x_train_channeld], y_train, batch_size=args.batch_size, epochs=args.epochs,
              validation_data=[[x_test_channelb, x_test_channelc, x_test_channeld], y_test], callbacks=[log, tb, checkpoint, lr_decay])
    # model.fit([x_train_channelb, x_train_channelc, x_train_channeld], y_train, batch_size=args.batch_size, epochs=args.epochs,
    #           validation_data=[[x_test_channelb, x_test_channelc, x_test_channeld], y_test], callbacks=[log, tb, checkpoint, lr_decay, WandbCallback()])

    model.save_weights(args.save_dir + '/trained_model.h5')
    # model.save(os.path.join(wandb.run.dir, "model.h5"))
    print('Trained model saved to \'%s/trained_model.h5\'' % args.save_dir)

    from utils import plot_log
    plot_log(args.save_dir + '/log.csv', show=True)

    return model


def test(model, data, args):
    ([x_test_channelb, x_test_channelc, x_test_channeld], y_test) = data
    y_pred = model.predict([x_test_channelb, x_test_channelc, x_test_channeld], batch_size=100)
    print('-'*30 + 'Begin: test' + '-'*30)
    print('Test acc:', np.sum(np.argmax(y_pred, 1) == np.argmax(y_test, 1))/y_test.shape[0])

    predictions = model.predict([x_test_channelb, x_test_channelc, x_test_channeld])
    pred = np.array(predictions)

    y_pred = np.argmax(pred, axis=1)
    y_test = np.argmax(y_test, axis=1)

    print('Confusion Matrix')
    print(confusion_matrix(y_test,y_pred))
    print('Classification Report')
    print(classification_report(y_test, y_pred, target_names=['noObject','circle','square','rect','Lrect','triangle']))

    print('-' * 30 + 'End: test' + '-' * 30)

def load_mydata(CONSTRUCTION_METHOD,NUMBER_OF_CLASSES,csv_filepath,data_filepath):
    
    if CONSTRUCTION_METHOD == 'image':
        train_df, input_shape = data_from_csv(csv_filepath, data_filepath)
        print('Create Tensor Data...')
        x_train_channelb = read_images(train_df.channelb.values, input_shape)
        x_train_channelc = read_images(train_df.channelc.values, input_shape)
        x_train_channeld = read_images(train_df.channeld.values, input_shape)
    else:
        train_df, input_shape = data_from_csv_nonimage(csv_filepath, data_filepath)
        x_train_channelb = read_data(train_df.channelb.values, input_shape)
        x_train_channelc = read_data(train_df.channelc.values, input_shape)
        x_train_channeld = read_data(train_df.channeld.values, input_shape)

    # labels - convert class vectors to binary class matrices One Hot Encoding
    labels = train_df.object.values
    labels = to_categorical(labels, NUMBER_OF_CLASSES)

    x_train_comp = np.stack((x_train_channelb, x_train_channelc, x_train_channeld), axis=4)

    x_train, x_test, y_train, y_test = train_test_split(x_train_comp, labels, test_size = 0.3, random_state=None)

    return (x_train, y_train), (x_test, y_test)

if __name__ == "__main__":
    import os
    import argparse
    from keras.preprocessing.image import ImageDataGenerator
    from keras import callbacks

    # setting the hyper parameters
    parser = argparse.ArgumentParser(description="Capsule Network on MNIST.")
    parser.add_argument('--epochs', default=2, type=int)
    parser.add_argument('--batch_size', default=10, type=int)
    parser.add_argument('--lr', default=0.001, type=float,
                        help="Initial learning rate")
    parser.add_argument('--lr_decay', default=0.9, type=float,
                        help="The value multiplied by lr at each epoch. Set a larger value for larger epochs")
    parser.add_argument('--lam_recon', default=0.392, type=float,
                        help="The coefficient for the loss of decoder")
    parser.add_argument('-r', '--routings', default=3, type=int,
                        help="Number of iterations used in routing algorithm. should > 0")
    parser.add_argument('--shift_fraction', default=0.1, type=float,
                        help="Fraction of pixels to shift at most in each direction.")
    parser.add_argument('--debug', action='store_true',
                        help="Save weights by TensorBoard")
    parser.add_argument('--save_dir', default='./CapsNet/result')
    parser.add_argument('-t', '--testing', action='store_true',
                        help="Test the trained model on testing dataset")
    parser.add_argument('--digit', default=5, type=int,
                        help="Digit to manipulate")
    parser.add_argument('-w', '--weights', default=None,
                        help="The path of the saved weights. Should be specified when testing")
    args = parser.parse_args()
    print(args)

    if not os.path.exists(args.save_dir):
        os.makedirs(args.save_dir)

    # load data
    (x_train, y_train), (x_test, y_test) = load_mydata(CONSTRUCTION_METHOD,NUMBER_OF_CLASSES,csv_filepath,data_filepath)
    x_train_channelb = x_train[:,:,:,:,0]
    x_test_channelb = x_test[:,:,:,:,0]
    x_train_channelc = x_train[:,:,:,:,1]
    x_test_channelc = x_test[:,:,:,:,1]
    x_train_channeld = x_train[:,:,:,:,2]
    x_test_channeld = x_test[:,:,:,:,2]

    # define model
    model, eval_model = CapsNet(input_shape=x_train_channelb.shape[1:],
                                                  n_class=len(np.unique(np.argmax(y_train, 1))),
                                                  routings=args.routings)
    model.summary()

    # train or test
    if args.weights is not None:  # init the model weights with provided one
        model.load_weights(args.weights)
    if not args.testing:
        train(model=model, data=(([x_train_channelb, x_train_channelc, x_train_channeld], y_train), ([x_test_channelb, x_test_channelc, x_test_channeld], y_test)), args=args)
    else:  # as long as weights are given, will run testing
        if args.weights is None:
            print('No weights are provided. Will test using random initialized weights.')
        test(model=eval_model, data=([x_test_channelb, x_test_channelc, x_test_channeld], y_test), args=args)
