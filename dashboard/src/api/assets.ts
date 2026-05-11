import { uploadImageBase64 } from './client'
import type { UploadedAsset } from '../types'

/**
 * Robustly uploads a file to the local agent and returns a standard UploadedAsset.
 * Handles FileReader promises and API errors.
 */
export async function handleAssetUpload(file: File): Promise<UploadedAsset> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.readAsDataURL(file)
    
    reader.onload = async () => {
      try {
        const base64 = reader.result as string
        // Strip data:image/...;base64, prefix if needed (though backend handles both)
        const res = await uploadImageBase64(base64, file.name)
        
        resolve({
          mediaId: res.media_id,
          fileName: file.name,
          previewUrl: base64
        })
      } catch (error) {
        console.error('[AssetUpload] API Error:', error)
        reject(error)
      }
    }
    
    reader.onerror = (error) => {
      console.error('[AssetUpload] FileReader Error:', error)
      reject(error)
    }
  })
}
