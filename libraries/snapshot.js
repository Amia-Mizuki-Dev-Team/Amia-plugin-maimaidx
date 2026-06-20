() => {
    const canvas = document.querySelector('canvas');
    if (canvas) {
        return canvas.toDataURL('image/png');
    }
    return '';
}
