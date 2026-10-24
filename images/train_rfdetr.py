"""Train RF-DETR on a Roboflow COCO export, on a machine with an NVIDIA GPU (e.g. the college RTX 5090).

The dataset folder is the unzipped "COCO JSON" export of the Roboflow version:
    <dataset>/train/_annotations.coco.json + images, valid/..., test/...
Roboflow puts the parent class "components" at id 0, then the parts A-Z - the same layout the
kiosk's config.py expects, so the trained model drops straight into the existing pipeline.

    py train_rfdetr.py --dataset dataset_v3_coco
    py train_rfdetr.py --dataset dataset_v3_coco --size small --epochs 100 --batch 16

Output: <out>/checkpoint_best_total.pth  - pass it to test_model.py and kiosk_app/export_onnx.py
"""
import argparse
from pathlib import Path

MODEL_CLASSES = {"nano": "RFDETRNano", "small": "RFDETRSmall", "medium": "RFDETRMedium", "base": "RFDETRBase"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, help="unzipped Roboflow COCO export")
    parser.add_argument("--size", default="small", choices=MODEL_CLASSES)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=16, help="16 fits a 32 GB RTX 5090 at 512 px; lower it if CUDA runs out of memory")
    parser.add_argument("--accum", type=int, default=1, help="gradient accumulation; batch x accum = effective batch")
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--out", default=None, help="output folder (default: runs/<size>_<dataset name>)")
    args = parser.parse_args()

    import torch
    import rfdetr

    if not torch.cuda.is_available():
        raise SystemExit("PyTorch can't see a GPU - install the CUDA build of torch (see README steps) before training.")
    print(f"GPU: {torch.cuda.get_device_name(0)}  torch {torch.__version__}  rfdetr {rfdetr.__version__}")

    dataset = Path(args.dataset)
    for split in ("train", "valid"):
        if not (dataset / split / "_annotations.coco.json").exists():
            raise SystemExit(f"{dataset / split / '_annotations.coco.json'} missing - export the version as COCO JSON.")

    out = Path(args.out or f"runs/{args.size}_{dataset.name}")
    model = getattr(rfdetr, MODEL_CLASSES[args.size])()      # starts from the COCO-pretrained checkpoint
    model.train(
        dataset_dir=str(dataset),
        epochs=args.epochs,
        batch_size=args.batch,
        grad_accum_steps=args.accum,
        lr=args.lr,
        output_dir=str(out),
        early_stopping=True,
        tensorboard=True,
    )
    print(f"\nDone. Best weights: {out / 'checkpoint_best_total.pth'}")


if __name__ == "__main__":      # required on Windows: the data loader starts worker processes
    main()
