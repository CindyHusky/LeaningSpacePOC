#updates: 
#long term actually does stuff now
#applyed smoothing to long term to allow for more perceptron data bleed


import cv2
import numpy as np

# === PARAMETERS ===
# Learning space parameters
LEARNING_SPACE_SIZE = (512, 512)  # (width, height)
DECAY_LEARNING = 0.98             # How quickly the learning space fades (per frame)

# Advanced blending parameters
BASE_BLEND = 0.90                 # Base weight for the existing learning space
NOVEL_BLEND = 0.10                # Additional weight given to areas deemed novel
DIFF_THRESHOLD = 30               # Pixel difference threshold (0-255) to consider a change as novel

# Novelty/reward parameters
PREDICTION_THRESHOLD = 0.5        # Threshold for histogram difference to be considered novel
CURIOSITY_FACTOR = 0.05           # Multiplier for the novelty to compute reward

# Long-term memory parameters
DECAY_FACTOR = 0.99               # Factor by which old memories fade
MAX_MEMORY = 100                  # Maximum number of images stored in memory

# Memory recall parameters (for human-like, reconstructive recall)
SIMILARITY_THRESHOLD = 15         # Minimum similarity threshold for a memory to be relevant
SIMILARITY_SCALE = 50.0           # Scale factor for converting histogram differences to similarity weights

# === INITIAL SETUP ===
learning_space = np.zeros(LEARNING_SPACE_SIZE, dtype=np.float32)
long_term_memory = []

# === HELPER FUNCTIONS ===

def calc_normalized_histogram(image):
    """
    Calculate a normalized histogram (256 bins) for an image.
    The image is assumed to be in uint8 format.
    """
    hist = cv2.calcHist([image], [0], None, [256], [0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    return hist

def calculate_histogram_novelty(current_frame, memory_frames):
    """
    Calculate novelty by comparing the histogram of the current frame
    to those of each stored memory frame. Returns the average L1 norm
    of the histogram differences.
    """
    hist_current = calc_normalized_histogram(current_frame)
    novelty_scores = []
    for mem_frame in memory_frames:
        mem_uint8 = mem_frame.astype(np.uint8)
        hist_mem = calc_normalized_histogram(mem_uint8)
        diff = np.sum(np.abs(hist_current - hist_mem))
        novelty_scores.append(diff)
    return np.mean(novelty_scores) if novelty_scores else 0

def calculate_curiosity_reward(current_state, memory_frames):
    """
    Calculate a curiosity reward based on histogram novelty.
    Returns both the reward and the raw novelty score.
    """
    novelty = calculate_histogram_novelty(current_state, memory_frames)
    reward = novelty * CURIOSITY_FACTOR if novelty > PREDICTION_THRESHOLD else 0
    return reward, novelty

def advanced_explore_learning_space(learning_space, new_frame):
    """
    Update the learning space with an advanced method:
      1. Decay the current learning space.
      2. Compute the pixelwise absolute difference between the new frame
         and the decayed learning space.
      3. Create a mask from differences that exceed DIFF_THRESHOLD.
      4. Update the learning space more strongly in regions of high novelty.
      5. Optionally, smooth the result for a more network-like appearance.
    """
    new_frame_float = new_frame.astype(np.float32)
    decayed = learning_space * DECAY_LEARNING
    diff = cv2.absdiff(new_frame_float, decayed)
    _, mask = cv2.threshold(diff, DIFF_THRESHOLD, 1, cv2.THRESH_BINARY)
    updated = decayed * BASE_BLEND + new_frame_float * (1 - BASE_BLEND + mask * NOVEL_BLEND)
    updated = cv2.GaussianBlur(updated, (3, 3), 0)
    return updated

def recall_similar_memories(current_state, memory_frames):
    """
    Mimic human-like memory recall by reconstructing a composite memory
    that is a weighted blend of stored memories, then apply additional smoothing
    to reduce sharpness and simulate the vagueness of human memory recall.
    """
    current_uint8 = current_state.astype(np.uint8)
    hist_current = calc_normalized_histogram(current_uint8)
    
    weighted_memories = []
    for mem in memory_frames:
        mem_uint8 = mem.astype(np.uint8)
        hist_mem = calc_normalized_histogram(mem_uint8)
        diff = np.sum(np.abs(hist_current - hist_mem))
        weight = np.exp(-diff / SIMILARITY_SCALE)
        if weight > np.exp(-SIMILARITY_THRESHOLD / SIMILARITY_SCALE):
            weighted_memories.append((weight, mem.astype(np.float32)))
    
    if not weighted_memories:
        return None

    total_weight = sum(w for w, _ in weighted_memories)
    composite_memory = np.zeros_like(current_state, dtype=np.float32)
    for weight, mem in weighted_memories:
        composite_memory += mem * (weight / total_weight)
    
    # Apply extra smoothing to mimic the vagueness of human memory recall.
    composite_memory = cv2.GaussianBlur(composite_memory, (5, 5), 0)
    
    return composite_memory

def update_long_term_memory(memory, current_state):
    """
    Update the long-term memory with the current state.
    Memories are first decayed, then:
      - If there is room, add the new state.
      - If at capacity, compare histogram differences and importance to decide
        whether to replace the least "important" memory.
    """
    decayed_memory = [state * DECAY_FACTOR for state in memory]
    current_float = current_state.astype(np.float32)
    
    if len(decayed_memory) < MAX_MEMORY:
        decayed_memory.append(current_float)
        print(f"Memory added. Total memories: {len(decayed_memory)}.")
    else:
        hist_current = calc_normalized_histogram(current_float.astype(np.uint8))
        hist_list = [calc_normalized_histogram(mem.astype(np.uint8)) for mem in decayed_memory]
        hist_array = np.stack(hist_list, axis=0)
        
        diffs = np.sum(np.abs(hist_array - hist_current), axis=1)
        novelty_new = np.mean(diffs)
        
        pairwise = np.sum(np.abs(hist_array[:, None, :] - hist_array[None, :, :]), axis=2)
        importance = (np.sum(pairwise, axis=1) - np.diag(pairwise)) / (len(decayed_memory) - 1)
        
        min_index = np.argmin(importance)
        min_importance = importance[min_index]
        
        if novelty_new > min_importance:
            decayed_memory[min_index] = current_float
            print(f"Replaced memory at index {min_index}: New novelty {novelty_new:.2f} > old importance {min_importance:.2f}.")
        else:
            print(f"New state novelty ({novelty_new:.2f}) did not exceed minimum stored importance ({min_importance:.2f}). No replacement.")
    
    return decayed_memory

# === MAIN LOOP ===

cap = cv2.VideoCapture(0)
if not cap.isOpened():
    print("Error: Could not open video capture device.")
    exit(1)

frame_count = 0
while True:
    ret, frame = cap.read()
    if not ret:
        print("Error: Failed to capture frame.")
        break

    frame_count += 1
    frame_resized = cv2.resize(frame, LEARNING_SPACE_SIZE, interpolation=cv2.INTER_AREA)
    gray_frame = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2GRAY)

    learning_space = advanced_explore_learning_space(learning_space, gray_frame)
    curiosity_reward, raw_novelty = calculate_curiosity_reward(gray_frame, long_term_memory)
    if curiosity_reward > 0:
        print(f"[Frame {frame_count}] Novelty reward: {curiosity_reward:.3f} (raw novelty: {raw_novelty:.3f})")
    
    composite_memory = recall_similar_memories(gray_frame, long_term_memory)
    if composite_memory is not None:
        cv2.imshow('Recalled Memory (Composite)', composite_memory.astype(np.uint8))
        print(f"[Frame {frame_count}] Recalled composite memory from {len(long_term_memory)} stored memories.")
    else:
        cv2.imshow('Recalled Memory (Composite)', np.zeros_like(gray_frame))
    
    long_term_memory = update_long_term_memory(long_term_memory, gray_frame)
    cv2.imshow('Learning Space', learning_space.astype(np.uint8))
    cv2.imshow('Current Frame', gray_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
