"""
Optuna example that demonstrates a pruner for PyTorch Ignite.

In this example, we optimize the validation accuracy of hand-written digit recognition using
PyTorch Ignite and MNIST, where the neural network architecture and the regularization is
optimized. Throughout the training of neural networks, a pruner observes intermediate results and
stops unpromising trials.

You can run this example as follows:
    $ python ignite_integration.py

"""
from __future__ import division
from __future__ import print_function

from ignite.engine import create_supervised_evaluator
from ignite.engine import create_supervised_trainer
from ignite.engine import Events
from ignite.metrics import Accuracy
import torch
from torch import nn
import torch.nn.functional as F
from torch.optim import Adam
from torch.utils.data import DataLoader
from torch.utils.data import Subset
from torchvision.datasets.mnist import MNIST
from torchvision.transforms import Compose
from torchvision.transforms import Normalize
from torchvision.transforms import ToTensor

import optuna


EPOCHS = 10
TRAIN_BATCH_SIZE = 64
VAL_BATCH_SIZE = 1000
N_TRAIN_EXAMPLES = 3000
N_VALID_EXAMPLES = 1000


class Net(nn.Module):
    def __init__(self, trial):
        # We optimize dropout rate in a convolutional neural network.
        super(Net, self).__init__()
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        dropout_rate = trial.suggest_uniform('dropout_rate', 0, 1)
        self.conv2_drop = nn.Dropout2d(p=dropout_rate)
        fc2_input_dim = trial.suggest_int('fc2_input_dim', 40, 80)
        self.fc1 = nn.Linear(320, fc2_input_dim)
        self.fc2 = nn.Linear(fc2_input_dim, 10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x), 2))
        x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training=self.training)
        x = self.fc2(x)
        return F.log_softmax(x, dim=-1)


def get_data_loaders(train_batch_size, val_batch_size):
    data_transform = Compose([ToTensor(), Normalize((0.1307,), (0.3081,))])

    train_data = MNIST(download=True, root=".", transform=data_transform, train=True)
    val_data = MNIST(download=False, root=".", transform=data_transform, train=False)

    train_loader = DataLoader(Subset(train_data, range(N_TRAIN_EXAMPLES)),
                              batch_size=train_batch_size, shuffle=True)
    val_loader = DataLoader(Subset(val_data, range(N_VALID_EXAMPLES)),
                            batch_size=val_batch_size, shuffle=False)

    return train_loader, val_loader


def objective(trial):
    # Create a convolutional neural network.
    model = Net(trial)

    device = 'cpu'
    if torch.cuda.is_available():
        device = 'cuda'

    optimizer = Adam(model.parameters())
    trainer = create_supervised_trainer(model, optimizer, F.nll_loss, device=device)
    evaluator = create_supervised_evaluator(model,
                                            metrics={'accuracy': Accuracy()},
                                            device=device)

    # Create another evaluator which calls pruning handler.
    pruning_evaluator = create_supervised_evaluator(model,
                                                    metrics={'accuracy': Accuracy()},
                                                    device=device)
    pruning_handler = optuna.integration.IgnitePruningHandler(trial, 'accuracy', trainer)
    pruning_evaluator.add_event_handler(Events.COMPLETED, pruning_handler)

    # Load MNIST dataset.
    train_loader, val_loader = get_data_loaders(TRAIN_BATCH_SIZE, VAL_BATCH_SIZE)

    @trainer.on(Events.EPOCH_COMPLETED)
    def log_results(engine):
        evaluator.run(train_loader)
        train_acc = evaluator.state.metrics['accuracy']
        pruning_evaluator.run(val_loader)
        validation_acc = pruning_evaluator.state.metrics['accuracy']
        print(
            "Epoch: {}  Train accuracy: {:.2f}  Validation accuracy: {:.2f}"
            .format(engine.state.epoch, train_acc, validation_acc)
        )

    trainer.run(train_loader, max_epochs=EPOCHS)

    evaluator.run(val_loader)
    return evaluator.state.metrics['accuracy']


if __name__ == "__main__":
    study = optuna.create_study(direction='maximize')
    study.optimize(objective, n_trials=100, timeout=600)

    print('Number of finished trials: ', len(study.trials))

    print('Best trial:')
    trial = study.best_trial

    print('  Value: ', trial.value)

    print('  Params: ')
    for key, value in trial.params.items():
        print('    {}: {}'.format(key, value))
