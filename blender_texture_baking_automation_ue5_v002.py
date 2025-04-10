import bpy
import os
from mathutils import Vector

class TextureBaker:
    def __init__(self):
        self.texture_size = 2048
        self.samples = 512
        self.bake_types = {
            'DIFFUSE': 'diffuse',
            'NORMAL': 'normal',
            'ROUGHNESS': 'roughness',
            'AO': 'ao',
            'EMIT': 'metallic'  # Metallic needs special handling
        }

    def get_bake_output_path(self):
        """Get output path for baked textures"""
        blend_file_path = bpy.data.filepath
        if not blend_file_path:
            raise Exception("Please save the blend file first")
        
        blend_dir = os.path.dirname(blend_file_path)
        output_path = os.path.join(blend_dir, "BakedTextures")
        
        if not os.path.exists(output_path):
            os.makedirs(output_path)
            
        return output_path

    def organize_textures_by_object(self, obj_name, output_path):
        """Create separate texture folders for each object"""
        obj_texture_path = os.path.join(output_path, obj_name)
        if not os.path.exists(obj_texture_path):
            os.makedirs(obj_texture_path)
        return obj_texture_path

    def setup_bake_settings(self):
        """Setup optimal baking parameters"""
        context = bpy.context
        scene = context.scene
        
        scene.render.engine = 'CYCLES'
        
        scene.cycles.samples = self.samples
        
        # Try to use GPU
        if hasattr(bpy.context.preferences.addons['cycles'].preferences, 'get_devices_for_type'):
            preferences = bpy.context.preferences
            cycles_preferences = preferences.addons['cycles'].preferences
            
            # Check available devices
            cuda_available = hasattr(cycles_preferences, 'get_devices_for_type') and cycles_preferences.get_devices_for_type('CUDA')
            optix_available = hasattr(cycles_preferences, 'get_devices_for_type') and cycles_preferences.get_devices_for_type('OPTIX')
            
            if optix_available:
                scene.cycles.device = 'GPU'
                cycles_preferences.compute_device_type = 'OPTIX'
                print("Using OptiX GPU acceleration")
            elif cuda_available:
                scene.cycles.device = 'GPU'
                cycles_preferences.compute_device_type = 'CUDA'
                print("Using CUDA GPU acceleration")
            else:
                scene.cycles.device = 'CPU'
                print("Using CPU rendering")
        
        # Set performance related parameters
        if hasattr(scene.render, 'tile_x'):  # Old Blender versions
            scene.render.tile_x = 512
            scene.render.tile_y = 512
        elif hasattr(scene.cycles, 'tile_size'):  # New Blender versions
            scene.cycles.tile_size = 512
        
        # Ensure nodes are used
        scene.use_nodes = True

    def setup_bake_nodes(self, material):
        """Setup necessary nodes for baking in the material"""
        material.use_nodes = True
        nodes = material.node_tree.nodes
        
        # Remove existing bake nodes
        existing = nodes.get('Bake_Target')
        if existing:
            nodes.remove(existing)
        
        # Create new bake node
        bake_node = nodes.new('ShaderNodeTexImage')
        bake_node.name = 'Bake_Target'
        bake_node.select = True
        nodes.active = bake_node
        
        return bake_node

    def create_bake_image(self, name, size):
        """Create image for baking"""
        # Check if image already exists
        existing = bpy.data.images.get(name)
        if existing:
            bpy.data.images.remove(existing)
            
        image = bpy.data.images.new(
            name=name,
            width=size,
            height=size,
            alpha=True,
            float_buffer=True
        )
        return image

    def validate_uv_maps(self, obj):
        """Validate UV unwrapping"""
        if not obj.data.uv_layers:
            raise Exception(f"{obj.name} has no UV maps")
        
        # Check if UVs are valid
        for uv_layer in obj.data.uv_layers:
            for polygon in obj.data.polygons:
                for loop_index in polygon.loop_indices:
                    uv_coords = obj.data.uv_layers.active.data[loop_index].uv
                    if uv_coords.x == 0 and uv_coords.y == 0:
                        print(f"Warning: {obj.name} might have unwrapped UVs")
                        return False
        return True

    def show_progress(self, current, total, prefix=''):
        """Display progress bar"""
        progress = int((current / total) * 100)
        bar_length = 50
        filled_length = int(bar_length * current // total)
        bar = '=' * filled_length + '-' * (bar_length - filled_length)
        print(f"\r{prefix} [{bar}] {progress}% [{current}/{total}]", end='')
        if current == total:
            print()

    def validate_object(self, obj):
        """Validate if object is valid for baking"""
        if not obj.data:
            print(f"Warning: {obj.name} has no mesh data")
            return False
            
        if len(obj.data.polygons) == 0:
            print(f"Warning: {obj.name} has no faces")
            return False
            
        if not obj.material_slots:
            print(f"Warning: {obj.name} has no materials")
            return False
            
        # Check for empty material slots
        for slot in obj.material_slots:
            if not slot.material:
                print(f"Warning: {obj.name} has empty material slots")
                return False
                
        # Check UV
        if not obj.data.uv_layers:
            print(f"Warning: {obj.name} has no UV layers")
            return False
            
        return True

    def setup_metallic_nodes(self, material):
        """Setup nodes for metallic baking"""
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        
        # Store original node connections for later restoration
        original_links = []
        for link in material.node_tree.links:
            original_links.append((link.from_socket, link.to_socket))
        
        # Create emission shader node
        emit = nodes.new('ShaderNodeEmission')
        
        # Get or create Material Output node
        output = nodes.get('Material Output')
        if not output:
            output = nodes.new('ShaderNodeOutputMaterial')
            output.name = 'Material Output'
        
        # Find Principled BSDF node
        principled = None
        for node in nodes:
            if node.type == 'BSDF_PRINCIPLED':
                principled = node
                break
        
        if not principled:
            print(f"Warning: No Principled BSDF node found in material {material.name}")
            # Create a new Principled BSDF node
            principled = nodes.new('ShaderNodeBsdfPrincipled')
        
        if principled:
            # Connect Metallic to Emission
            metallic_socket = principled.inputs['Metallic']
            if metallic_socket.is_linked:
                # If Metallic is already connected to an input, use that input
                links.new(metallic_socket.links[0].from_socket, emit.inputs['Strength'])
            else:
                # If it's a fixed value, create a Value node
                value = nodes.new('ShaderNodeValue')
                value.outputs[0].default_value = metallic_socket.default_value
                links.new(value.outputs[0], emit.inputs['Strength'])
        
        # Connect Emission to output
        links.new(emit.outputs[0], output.inputs['Surface'])
        
        return original_links

    def restore_material_links(self, material, original_links):
        """Restore original material connections"""
        # Clear temporary nodes
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        
        # Remove previously created temporary nodes
        for node in nodes:
            if node.type in ['EMISSION', 'VALUE']:
                nodes.remove(node)
        
        # Restore original connections
        for from_socket, to_socket in original_links:
            links.new(from_socket, to_socket)

    def bake_textures(self, obj, output_path):
        """Execute texture baking"""
        try:
            if not self.validate_object(obj):
                print(f"Skipping {obj.name} - Object validation failed")
                return False
                
            obj_texture_path = self.organize_textures_by_object(obj.name, output_path)
            
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            
            materials = [slot.material for slot in obj.material_slots if slot.material]
            
            if not materials:
                print(f"Warning: {obj.name} has no valid materials")
                return False
            
            # Create one bake node for each texture type
            total_bakes = len(self.bake_types)
            current_bake = 0
            
            # Setup bake nodes for all materials
            bake_nodes = []
            for material in materials:
                if not material.use_nodes:
                    material.use_nodes = True
                bake_node = self.setup_bake_nodes(material)
                bake_nodes.append(bake_node)
            
            # Bake each texture type once
            for bake_type, suffix in self.bake_types.items():
                current_bake += 1
                self.show_progress(
                    current_bake, 
                    total_bakes, 
                    f"Baking {obj.name} - {suffix}"
                )
                
                # Create a unified texture
                image_name = f"{obj.name}_{suffix}"
                bake_image = self.create_bake_image(image_name, self.texture_size)
                
                # Set the same bake target image for all materials
                for bake_node in bake_nodes:
                    bake_node.image = bake_image
                
                # Special handling for metallic maps
                original_links = []
                if suffix == 'metallic':
                    for material in materials:
                        links = self.setup_metallic_nodes(material)
                        original_links.append((material, links))
                    bake_type = 'EMIT'
                
                try:
                    # Execute baking
                    bpy.ops.object.bake(type=bake_type)
                    
                    # Save image
                    image_path = os.path.join(obj_texture_path, f"{image_name}.png")
                    bake_image.save_render(image_path)
                    print(f"\nSuccessfully saved: {image_path}")
                    
                finally:
                    # Restore original material settings for metallic maps
                    if suffix == 'metallic':
                        for material, links in original_links:
                            self.restore_material_links(material, links)
            
            return True
            
        except Exception as e:
            print(f"Error during baking {obj.name}: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return False

    def cleanup_bake_nodes(self):
        """Clean up temporary bake nodes"""
        for material in bpy.data.materials:
            if material.node_tree:
                nodes = material.node_tree.nodes
                bake_nodes = [n for n in nodes if n.name.startswith('Bake_Target')]
                for node in bake_nodes:
                    nodes.remove(node)

    def execute(self):
        """Execute complete baking process"""
        try:
            print("Starting texture baking process...")
            
            # Get output path
            output_path = self.get_bake_output_path()
            print(f"Output path: {output_path}")
            
            # Setup optimal baking parameters
            self.setup_bake_settings()
            print("Bake settings optimized")
            
            # Get all objects to bake and validate them
            all_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
            objects_to_bake = []
            
            print("Validating scene objects...")
            for obj in all_objects:
                if self.validate_object(obj):
                    objects_to_bake.append(obj)
                else:
                    print(f"Skipping invalid object: {obj.name}")
            
            if not objects_to_bake:
                raise Exception("No valid objects to bake in the scene")
            
            print(f"\nFound {len(objects_to_bake)} valid objects to bake")
            
            # Track success and failure counts
            success_count = 0
            fail_count = 0
            
            # Process all objects
            for i, obj in enumerate(objects_to_bake, 1):
                print(f"\nProcessing object {i}/{len(objects_to_bake)}: {obj.name}")
                
                if self.bake_textures(obj, output_path):
                    success_count += 1
                else:
                    fail_count += 1
            
            # Clean up temporary nodes
            self.cleanup_bake_nodes()
            
            print("\n=== Baking Task Complete ===")
            print(f"Success: {success_count} objects")
            print(f"Failed: {fail_count} objects")
            print(f"Textures saved to: {output_path}")
            
        except Exception as e:
            print(f"Error occurred: {str(e)}")
            import traceback
            print(traceback.format_exc())

def main():
    baker = TextureBaker()
    baker.execute()

if __name__ == "__main__":
    main()
