import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from sklearn.model_selection import KFold
from torch.multiprocessing import Pool, set_start_method
import argparse
import time
import os
import numpy as np

# We import vgg11 for CIFAR10:
from torchvision.models import vgg11

from train_p8020_EXT import train

from sklearn.model_selection import train_test_split

# Necessary for CUDA multiprocessing
set_start_method('spawn', force=True)

############################################
# LeNet definition for MNIST (unchanged)
############################################
class LeNet(nn.Module):
    def __init__(self):
        super(LeNet, self).__init__()
        self.conv1 = nn.Conv2d(1, 6, 5)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.fc1 = nn.Linear(16*4*4, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, 10)

    def forward(self, x):
        x = torch.relu(nn.MaxPool2d(2)(self.conv1(x)))
        x = torch.relu(nn.MaxPool2d(2)(self.conv2(x)))
        x = x.view(-1, 16*4*4)
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        x = self.fc3(x)
        return x

def parallel_kfold():
    kf = KFold(n_splits=args.folds)
    start_time = time.time()  # Start the timer before initializing the pool

    # Parallel cross-validation
    with Pool(processes=args.processors) as pool:
        results = pool.starmap(
            train,
            [(fold, train_idx, val_idx, X, y, device, args)
             for fold, (train_idx, val_idx) in enumerate(kf.split(X))]
        )

    end_time = time.time()  # Stop the timer after the processing finishes
    elapsed_time = end_time - start_time  # Total elapsed time across processors
    return results, elapsed_time

def test_model(best_model, X_test, y_test, device):
    with torch.no_grad():
        X_test = torch.tensor(X_test, dtype=torch.float32).to(device)
        y_test = torch.tensor(y_test, dtype=torch.int64).to(device)
        outputs = best_model(X_test)
        test_accuracy = (outputs.argmax(1) == y_test).float().mean().item()
    return test_accuracy

def main():
    # Split the data into training and testing (80-20%)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )
    print(f"*** The dataset has been split in 80% training with {len(y_train)} records "
          f"and 20% testing with {len(y_test)} records ***")

    start_time_total = time.time()  # Start the total processing timer

    if args.folds < 2:
        print("Folds is set to 1. Skipping cross-validation and training on the entire training set.")

        # Choose the architecture based on --ds
        if args.ds.upper() == "MNIST":
            model = LeNet().to(device)
        else:
            # For CIFAR10, use VGG-11
            model = vgg11(num_classes=10).to(device)

        criterion = nn.CrossEntropyLoss()
        optimizer = optim.SGD(model.parameters(), lr=args.lr)

        # Convert tensors and move to device
        X_train_tensor = torch.tensor(X_train, dtype=torch.float32).to(device)
        y_train_tensor = torch.tensor(y_train, dtype=torch.int64).to(device)

        train_dataset = torch.utils.data.TensorDataset(X_train_tensor, y_train_tensor)
        train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)

        # Train
        start_time_train = time.time()
        for epoch in range(args.epochs):
            for batch_X, batch_y in train_loader:
                optimizer.zero_grad()
                outputs = model(batch_X)
                loss = criterion(outputs, batch_y)
                loss.backward()
                optimizer.step()
        end_time_train = time.time()

        elapsed_time_train = end_time_train - start_time_train

        # Test
        start_time_test = time.time()
        test_accuracy = test_model(model, X_test, y_test, device)
        end_time_test = time.time()
        elapsed_time_test = end_time_test - start_time_test

        print(f"Training complete. Training time: {elapsed_time_train:.4f} seconds. "
              f"Testing time: {elapsed_time_test:.4f} seconds.")
        print(f"Testing accuracy: {test_accuracy * 100:.4f}%")
    else:
        # Perform k-fold cross-validation in parallel
        results, total_elapsed_time = parallel_kfold()

        losses = [result[0] for result in results]
        accuracies = [result[1] for result in results]
        best_model_idx = accuracies.index(max(accuracies))
        best_model = results[best_model_idx][2]

        test_accuracy = test_model(best_model, X_test, y_test, device)
        print(f"Average validation accuracy across folds: {sum(accuracies)/len(accuracies)*100:.4f}%")
        print(f"Testing accuracy using best model: {test_accuracy * 100:.4f}%")
        print(f"Total processing time across all folds: {total_elapsed_time:.4f} seconds.")

    end_time_total = time.time()
    total_processing_time = end_time_total - start_time_total
    print(f"Total processing time: {total_processing_time:.4f} seconds.")

if __name__ == '__main__':
    # Command line arguments
    parser = argparse.ArgumentParser(description="Parallel k-fold cross-validation on MNIST or CIFAR10")
    parser.add_argument('--gpu', action='store_true', help='Use GPU if available')
    parser.add_argument('--processors', type=int, default=2, help='Number of processors for parallel processing')
    parser.add_argument('--folds', type=int, default=10, help='Number of k-folds for cross-validation')
    parser.add_argument('--batch_size', type=int, default=64, help='Batch size for training')
    parser.add_argument('--epochs', type=int, default=10, help='Number of epochs')
    parser.add_argument('--lr', type=float, default=0.01, metavar='LR', help='Learning rate (default: 0.01)')

    # **New argument for dataset selection**
    parser.add_argument('--ds', type=str, default='MNIST',
                        help='Dataset to use: MNIST or CIFAR10')

    args = parser.parse_args()

    # Set device to GPU if available and requested
    device = torch.device("cuda" if args.gpu and torch.cuda.is_available() else "cpu")

    # Load the chosen dataset
    if args.ds.upper() == 'MNIST':
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.5,), (0.5,))
        ])
        dataset = datasets.MNIST(root='/root/sandbox/MASCIFAROK/MASOK/data', train=True, transform=transform, download=True)
        ## INGESTS THE DATASET CIFAR FROM MASCIFAR DATA DIRECTORY!!!
        X = dataset.data.numpy().reshape(-1, 1, 28, 28) / 255.0
        y = dataset.targets.numpy()
    elif args.ds.upper() == 'CIFAR10':
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))
        ])
        dataset = datasets.CIFAR10(root='./data', train=True, transform=transform, download=True)
        # CIFAR-10 data is HxWxC in dataset.data
        # Reshape to NxCxHxW and scale to [0,1]
        X = dataset.data.transpose((0, 3, 1, 2)) / 255.0
        y = np.array(dataset.targets)
    else:
        raise ValueError("Unsupported dataset. Use '--ds MNIST' or '--ds CIFAR10'.")

    main()
